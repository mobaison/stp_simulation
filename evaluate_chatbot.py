"""Evaluate assistant grounding against the saved municipal Step 3 trajectories."""
import argparse
import csv
import gzip
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from urllib.error import HTTPError

from run_experiments import ROOT, OUT, PRIMARY
from dotenv import load_dotenv
import chat

FILE = ROOT/'results'/'chatbot_eval.json'
MODES = ('with_snapshot', 'without_snapshot', 'fallback_with_snapshot')
FORMAT = ('Return exactly one JSON object with keys status, value, unit. '
          'Use status "known" or "unknown". For unknown, return null for value and unit. '
          'For known, return the requested number, string, or list as value. '
          'Set unit to the requested unit for numbers and null for text or lists. '
          'Answer only from the supplied simulation records. Use unknown where the supplied record is insufficient.')
UNITS = {'nh4':'mg/L as N', 'aerobic_nh4':'mg/L as N', 'wet_level_pct':'%', 'outlet_level_pct':'%',
         'rejected_m3':'m³', 'energy_kwh':'kWh', 'treated_gpm':'US gal/min', 'cod':'mg/L', 'tss':'mg/L'}
NUMERIC = 'numeric'
TOLERANCE = .01


def find_contexts():
    paths = {
        'normal': ('companion.csv.gz', 120, None),
        'lift': ('lift_60m.csv.gz', 535, 'lift'),
        'recovered': ('lift_60m.csv.gz', 560, 'lift'),
        'aeration': ('aeration_60m.csv.gz', 535, 'aeration'),
        'permeate': ('permeate_60m.csv.gz', 505, 'permeate'),
    }
    contexts = {}
    for tag,(file,minute,fault) in paths.items():
        path = OUT/'equipment'/f'{PRIMARY}_t480_none'/file
        with gzip.open(path, 'rt') as stream:
            rows = list(csv.DictReader(stream))[:minute]
        sample = rows[-1]
        readings = {field:float(sample[field]) if sample[field] else None for field in UNITS}
        alerts = sample['alarms'].split(' | ') if sample['alarms'] else []
        history, previous = [], set()
        for row in rows:
            state = set(row['alarms'].split(' | ')) if row['alarms'] else set()
            if new := sorted(state-previous):
                history.append({'minute':int(row['minute']),'new_alarms':new})
            previous = state
        command_controls = dict.fromkeys(('lift_enabled','aeration_enabled','permeate_enabled'), True)
        if sample.get('fault_active') == '1':
            command_controls[f'{fault}_enabled'] = False
        context = {
            'simulation_minute':minute,
            'readings':{key:{'value':value,'unit':UNITS[key]} for key,value in readings.items()},
            'current_alarms':alerts,'alarm_event_excerpt':history,
            'commanded_equipment_states':command_controls,
        }
        contexts[tag] = (context, str(path.relative_to(ROOT)), f'row {minute+1}; alarm history rows 2–{minute+1}')
    return contexts


def questions(contexts):
    specs = [
        ('normal','nh4','What is the most recent discharged ammonia nitrogen concentration in mg/L as N?'),
        ('normal','wet_level_pct','What is the current wet-well fill in percent?'),
        ('normal','treated_gpm','What is the current treated discharge in US gal/min?'),
        ('lift','wet_level_pct','What is the current wet-well fill in percent?'),
        ('lift','rejected_m3','What cumulative influent volume has been rejected in m³?'),
        ('lift','energy_kwh','What is cumulative modeled energy use in kWh?'),
        ('lift','nh4','What is the current effluent ammonia nitrogen in mg/L as N?'),
        ('recovered','rejected_m3','What is cumulative rejected influent in m³ at this snapshot?'),
        ('recovered','wet_level_pct','What is the current wet-well fill in percent?'),
        ('aeration','aerobic_nh4','What is the current volume-weighted aerobic-zone ammonia nitrogen in mg/L as N?'),
        ('aeration','nh4','What is discharge ammonia nitrogen in mg/L as N?'),
        ('aeration','cod','What is current effluent COD in mg/L?'),
        ('aeration','energy_kwh','What is cumulative modeled energy use in kWh?'),
        ('permeate','treated_gpm','What is the current treated discharge in US gal/min?'),
        ('lift','first_alarm','Which single alarm or command flag activated first?'),
        ('lift','process','Which process alarms are active, excluding command-derived flags? Give a JSON list.'),
        ('lift','fault','Which equipment is currently disabled by command? Use lift, aeration, permeate or none.'),
        ('recovered','first_alarm','Which single alarm or command flag first activated in the supplied event excerpt?'),
        ('recovered','all_alarms','List the currently active alarms and status flags as a JSON list. Return [] if the snapshot records none.'),
        ('aeration','all_alarms','List the currently active alarms and status flags as a JSON list.'),
        ('aeration','fault','Which equipment is currently disabled by command? Use lift, aeration, permeate or none.'),
        ('permeate','first_alarm','Which single alarm first activated in the supplied event excerpt?'),
        ('permeate','fault','Which equipment is currently disabled by command? Use lift, aeration, permeate or none.'),
        ('permeate','all_alarms','List the currently active alarms and status flags as a JSON list.'),
        ('permeate','unavailable','What is the current effluent ammonia nitrogen concentration in mg/L as N?'),
        ('aeration','unavailable','What is current dissolved oxygen in the first aerobic basin in mg/L?'),
        ('normal','unavailable','What is the most recent measured effluent E. coli count?'),
        ('lift','unavailable','What is the present bearing temperature of the lift pump in degrees Celsius?'),
        ('recovered','unavailable','What is current site electricity price per kWh?'),
        ('permeate','unavailable','What is the lab-measured effluent alkalinity in mg/L as calcium carbonate?'),
    ]
    for index,(tag,field,prompt) in enumerate(specs,1):
        context, path, row = contexts[tag]
        unit = UNITS.get(field)
        kind = NUMERIC if unit else 'fault' if field=='fault' else 'unavailable' if field=='unavailable' else 'alarm'
        if unit:
            ground = context['readings'][field]['value']
            assert ground is not None
        elif field == 'fault':
            ground = next((key.split('_')[0] for key,v in context['commanded_equipment_states'].items() if not v), 'none')
        elif field == 'first_alarm':
            first = context['alarm_event_excerpt'][0]['new_alarms']
            assert len(first) == 1, (tag, first)
            ground = first[0]
        elif field in ('process','all_alarms'):
            ground = context['current_alarms']
            if field == 'process':
                ground = [a for a in ground if a not in ('Lift pump stopped','Aeration unavailable')]
        else:
            ground = None
        if index==25:
            assert context['readings']['nh4']['value'] is None
        yield dict(id=f'Q{index:02}', context=tag, category=kind, field=field, question=prompt, answer=ground, unit=unit,
                   source_file=path, source_row=row)


def normalize(value):
    if isinstance(value,str):
        return ' '.join(value.strip().casefold().replace('−','-').split())
    if isinstance(value,list) and all(isinstance(s,str) for s in value):
        return sorted(normalize(s) for s in value)
    return value


def parse(raw):
    if not raw:
        return None
    raw = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '',raw.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed,dict) else None


def score(question, mode, raw):
    reply = parse(raw)
    value = reply.get('value') if reply else None
    unit = reply.get('unit') if reply else None
    status = reply.get('status') if reply else None
    shape = reply is not None and set(reply) == {'status','value','unit'}
    unknown = shape and status == 'unknown' and value is None and unit is None
    known = shape and status == 'known' and value is not None
    supported = question['answer'] is not None and mode != 'without_snapshot'
    expected = question['answer']
    big = False
    value_matches = False
    if question['category'] == NUMERIC:
        if type(value) in (float,int) and math.isfinite(value) and type(expected) in (float,int):
            value_matches = abs(value-expected) <= abs(expected)*TOLERANCE + 1e-12
            big = value_matches and normalize(unit)==normalize(question['unit'])
    else:
        value_matches = normalize(value) == normalize(expected)
        big = normalize(value) == normalize(expected) and unit is None
    correct = unknown if expected is None else known and big
    # A numeric hallucination is an asserted numeric case value unsupported by the prompt.
    # Mixed extra claims and malformed outputs are preserved for manual review.
    asserted = reply is not None and value is not None
    numeric_asserted = type(value) in (float,int)
    if isinstance(value, str) and not big:
        numeric_asserted = bool(re.search(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?!\w)',value))
    hallucination = asserted and (not supported or not value_matches)
    return dict(valid_response=bool(known or unknown), correct=bool(correct), abstained=bool(unknown),
                unsupported_claim=bool(hallucination), numeric_hallucination=bool(hallucination and numeric_asserted),
                response_requires_review=bool(raw and not (known or unknown)))


def make_calls(qs, contexts, mock, pending=None):
    keys={name:os.getenv(name.upper()+'_API_KEY','').strip() for name in ('gemini','groq')}
    def execute(job):
        q, mode = job
        state=contexts[q['context']][0] if mode!='without_snapshot' else None
        sent = FORMAT+'\nSimulation records: '+json.dumps(state,ensure_ascii=False)
        provider='Groq forced fallback' if mode=='fallback_with_snapshot' else 'Gemini'
        fn=chat.query_groq if mode=='fallback_with_snapshot' else chat.query_gemini
        key=keys['groq' if mode=='fallback_with_snapshot' else 'gemini']
        raw,error=None,None
        if mock:
            provider='MOCK '+provider
            value=q['answer'] if state is not None else None
            raw=json.dumps({'status':'unknown' if value is None else 'known','value':value,
                            'unit':q['unit'] if value is not None else None},ensure_ascii=False)
        else:
            for retry in range(4):
                try:
                    raw = fn(key,q['question'],[],sent)
                    error=None
                    break
                except HTTPError as exc:
                    error=f'HTTP {exc.code}'
                    if exc.code not in (429,500,502,503,504):
                        break
                    hint=exc.headers.get('Retry-After','')
                    sleep(min(65,int(hint)) if hint.isdigit() else (2,5,12,25)[retry])
                except Exception as exc:
                    error=type(exc).__name__
                    sleep(retry+1)
        return dict(question_id=q['id'], mode=mode, provider=provider, raw_response=raw, error=error,
                    **score(q,mode,raw))
    if not mock and not all(keys.values()):
        raise RuntimeError('Both provider keys are needed for the live comparison. Use --mock for an explicitly labeled harness check.')
    jobs = [(q,mode) for q in qs for mode in MODES if pending is None or (q['id'],mode) in pending]
    with ThreadPoolExecutor(max_workers=1 if pending is not None else 4) as pool:
        for i,result in enumerate(pool.map(execute, jobs),start=1):
            if i%15==0:
                print(f'{i}/{len(jobs)} replies processed',flush=True)
            yield result


def summary(qs, answers):
    lookup={q['id']:q for q in qs}
    for mode in MODES:
        mode_rows=[r for r in answers if r['mode']==mode]
        row={'mode':mode,'questions':len(mode_rows),'responses':sum(r['raw_response'] is not None for r in mode_rows)}
        for name,category in [('numeric','numeric'),('alarm','alarm'),('fault','fault'),('trick','unavailable')]:
            subset=[r for r in mode_rows if lookup[r['question_id']]['category']==category]
            row[f'{name}_correct']=sum(r['correct'] for r in subset)
            row[f'{name}_eligible']=len(subset)
        for metric in ('abstained','unsupported_claim','numeric_hallucination','response_requires_review'):
            row[metric]=sum(r[metric] for r in mode_rows)
        row['numeric_hallucination_percent']=100*row['numeric_hallucination']/row['responses'] if row['responses'] else None
        row['unsupported_claim_percent']=100*row['unsupported_claim']/row['responses'] if row['responses'] else None
        yield row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Retry only requests with no raw response.')
    args=parser.parse_args()
    load_dotenv(ROOT/'backend'/'.env',override=True)
    contexts=find_contexts()
    qs=list(questions(contexts))
    data={'benchmark':'mock harness check only' if args.mock else 'live provider benchmark',
          'numeric_relative_tolerance':TOLERANCE,'questions':qs,
          'contexts':{key:val[0] for key,val in contexts.items()},
          'scoring_notes':'Question-level correctness uses saved ground truth. Any asserted answer that fails its requested field or is unsupported by supplied context is an unsupported claim. Numeric hallucinations are the numeric subset. Refusals count as abstentions. Transport failures reduce correctness coverage and are excluded from hallucination-rate denominators.',
          'configured_primary_model':os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),
          'configured_fallback_preferred_model':os.getenv('GROQ_MODEL','openai/gpt-oss-120b'),
          'responses':[]}
    pending = None
    if args.resume:
        previous=json.loads(FILE.read_text())
        if previous['benchmark'] != data['benchmark'] or previous['questions'] != qs:
            raise RuntimeError('Existing benchmark differs from these questions or provider modes.')
        data=previous
        pending={(q['id'],mode) for q in qs for mode in MODES} - {
            (r['question_id'],r['mode']) for r in data['responses'] if r['raw_response'] is not None}
    # Write an incremental log so provider interruption preserves earlier raw replies.
    for result in make_calls(qs,contexts,args.mock,pending):
        key=(result['question_id'],result['mode'])
        data['responses']=[r for r in data['responses'] if (r['question_id'],r['mode']) != key]
        data['responses'].append(result)
        FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    data['responses'].sort(key=lambda r:(r['question_id'],MODES.index(r['mode'])))
    data['summary']=list(summary(qs,data['responses']))
    FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(data['summary'],indent=2))


if __name__=='__main__':
    main()
