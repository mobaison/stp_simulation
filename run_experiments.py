#!/usr/bin/env python3
"""Run the frozen Step 3 study from the separately verified v2 checkpoints."""
import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'backend'))
from engine import Controls, FIELDS, ORGANICS, SPEC, STAGE_REACTION_RATES_H, Twin

OUT = ROOT/'results'/'step3'
STATES = ROOT/'results'/'model_v2'
MANIFEST = STATES/'freeze_manifest.sha256'
DAY = 1440
STARTS = (120, 480, 960)
DURATIONS = (15, 60, 240)
FAULTS = ('lift', 'aeration', 'permeate')
CONDITIONS = tuple(f'{influent}_{rate}' for influent in ('municipal','default')
                   for rate in ('adopted','legacy','minus20','plus20'))
PRIMARY = 'municipal_adopted'
REDUCED = ('none', 'wet_50', 'outlet_50')
FULL = ('none', 'wet_25', 'wet_50', 'wet_75', 'outlet_25', 'outlet_50', 'outlet_75')
BIASES = (-.05, 0., .05)
SCHEDULES = ('constant','surge')
MODES = ('healthy','stuck','drift')
SEEDS = tuple(range(20))
NOISE_SIGMA = .5
SENSOR_START = 120
OUTLET_RISES = {'nh4': .5, 'cod': 5., 'bod': 2., 'tss': 1.}
STATUS_FLAGS = {'lift':'Lift pump stopped','aeration':'Aeration unavailable'}
GROUPS_EXPECTED = 84
FAULT_RUNS_EXPECTED = 756
SENSOR_RUNS_EXPECTED = 2880

PREFIXES = {}
CHECKPOINTS = {}


class StudyTwin(Twin):
    def snapshot(self):
        # Avoid constructing a dashboard payload for each research sample.
        # The inherited step updates all physical states, flows, and alarms.
        return None


class Sample(NamedTuple):
    minute: int
    treated_gpm: float
    nh4: float | None
    no3: float | None
    cod: float | None
    bod: float | None
    tss: float | None
    aerobic_nh4: float
    wet_level_pct: float
    outlet_level_pct: float
    energy_kwh: float
    rejected_m3: float
    recycle_kw: float
    water_balance_m3: float
    worst_constituent_balance_kg: float
    alarms: str


def read_checkpoint(condition):
    return json.loads((STATES/f'{condition}_verified_state.json').read_text())


def controls_for(checkpoint):
    return replace(Controls(**checkpoint['controls']), dt_s=60.)


def new_twin(checkpoint, state=None):
    start = checkpoint if state is None else state
    twin = StudyTwin()
    twin.reaction_rates_h = {key: values.copy() for key,values in STAGE_REACTION_RATES_H.items()}
    twin.reaction_rates_h['aero']['nh4'] = checkpoint['ammonia_rate_h']
    twin.volume = start['volume_m3'].copy()
    twin.mass = {key: values.copy() for key,values in start['mass_kg'].items()}
    twin.part = {key: values.copy() for key,values in start['particulate_mass_kg'].items()}
    for name in ('elapsed','energy','rejected','wasted'):
        setattr(twin, name, start.get(name, 0.))
    return twin


def capture(twin):
    return {
        'volume_m3':twin.volume.copy(), 'mass_kg':{k:v.copy() for k,v in twin.mass.items()},
        'particulate_mass_kg':{k:v.copy() for k,v in twin.part.items()},
        **{k:getattr(twin,k) for k in ('elapsed','energy','rejected','wasted')},
    }


def read_sample(twin):
    eff = twin.effluent_quality
    aero = tuple(f'aero{i}' for i in range(1,5))
    aero_v = sum(twin.volume[k] for k in aero)
    aero_n = sum(twin.mass[k]['nh4'] for k in aero)
    return Sample(int(twin.elapsed/60), twin.flows.get('treated_out',0.),
                  *(eff[k] for k in ('nh4','no3','cod','bod','tss')),
                  1000*aero_n/aero_v if aero_v else 0.,
                  100*twin.volume['lift']/SPEC['lift'].cap, 100*twin.volume['outlet']/SPEC['outlet'].cap,
                  twin.energy, twin.rejected, twin.last_recycle_power_kw, twin.mass_error,
                  max(abs(v) for v in twin.quality_error.values()), ' | '.join(twin.alerts))


def last_discharge(twin):
    volume = twin._flows['treated_out']
    return (None if volume <= 0 else (
        {f: twin._effluent_mass[f]/volume for f in FIELDS},
        {f: twin._effluent_particulate_mass[f]/volume for f in ORGANICS},
    ))


def prefix_for(condition):
    checkpoint = read_checkpoint(condition)
    controls = controls_for(checkpoint)
    twin = new_twin(checkpoint)
    rows = []
    seeds = {}
    sample = None
    for minute in range(1,max(STARTS)+1):
        twin.step(controls)
        rows.append(read_sample(twin))
        sample = last_discharge(twin) or sample
        if minute in STARTS:
            seeds[minute] = (capture(twin), sample)
    return condition, rows, seeds


def perturb(twin, name, effluent):
    if name == 'none':
        return
    tank_name, fraction = name.split('_')
    key = 'lift' if tank_name == 'wet' else 'outlet'
    volume = SPEC[key].cap * int(fraction)/100
    before = twin.volume[key]
    if before > 1e-12:
        for amounts in (twin.mass[key],twin.part[key]):
            for species in amounts:
                amounts[species] *= volume/before
    else:
        if key != 'outlet' or effluent is None:
            raise RuntimeError(f'Perturbation unavailable for {name}: no reference concentration')
        bulk,part = effluent
        twin.mass[key] = {f:c*volume for f,c in bulk.items()}
        twin.part[key] = {f:c*volume for f,c in part.items()}
    twin.volume[key] = volume


def effect(controls, fault):
    name, value = {'lift':('lift_on',False), 'aeration':('aeration',0.),
                   'permeate':('permeate_on',False)}[fault]
    return replace(controls, **{name:value})


def eligible_process(fault, alarms):
    if fault == 'lift':
        return {a for a in alarms if a in ('Facility lift station: HIGH LEVEL','Wet well: incoming sewage rejected')}
    if fault == 'permeate':
        return {a for a in alarms if a == 'Treated water holding tank: LOW LEVEL'
                or (a.startswith('Membrane tank ') and a.endswith(': HIGH LEVEL'))}
    return set()


def detect_equipment(rows, matched, fault, onset, duration):
    events = {'status':None,'process':None,'in_process':None,'outlet':None}
    previous = set()
    previous_aero = False
    for row,ref in zip(rows[onset:],matched[onset:]):
        delay = row.minute-onset
        alarms = set(row.alarms.split(' | '))
        new_process = eligible_process(fault, alarms-set(ref.alarms.split(' | ')))
        if events['status'] is None and STATUS_FLAGS.get(fault) in alarms:
            events['status'] = (delay, STATUS_FLAGS[fault], None, None)
        if events['process'] is None and new_process:
            events['process'] = (delay, ' | '.join(sorted(new_process)), None, None)
        signals = []
        if ref.treated_gpm > 0 and row.treated_gpm <= .90*ref.treated_gpm:
            signals.append('treated_gpm')
        for field,absolute in OUTLET_RISES.items():
            value, reference = getattr(row,field), getattr(ref,field)
            if value is not None and reference is not None and value-reference >= max(.20*reference,absolute):
                signals.append(field)
        if events['outlet'] is None:
            for field in signals:  # Tie priority is flow, NH4-N, COD, BOD, TSS.
                if field in previous:
                    events['outlet'] = (delay,field,getattr(row,field),getattr(ref,field))
                    break
        previous = set(signals)
        raised = row.aerobic_nh4-ref.aerobic_nh4 >= max(.20*ref.aerobic_nh4,.5)
        if events['in_process'] is None and previous_aero and raised:
            events['in_process'] = (delay,'aerobic_nh4',row.aerobic_nh4,ref.aerobic_nh4)
        previous_aero = raised
        if all(events.values()):
            break
    out = {}
    unavailable = {'status':fault not in STATUS_FLAGS, 'process':fault=='aeration'}
    for channel,result in events.items():
        if result:
            delay,signal,observed,reference = result
            out.update({f'{channel}_state':'detected', f'{channel}_delay_min':delay, f'{channel}_signal':signal,
                        f'{channel}_during_outage':delay<=duration,f'{channel}_observed':observed,
                        f'{channel}_matched_reference':reference})
        else:
            out.update({f'{channel}_state':'unavailable' if unavailable.get(channel) else 'right_censored',
                        f'{channel}_delay_min':None, f'{channel}_signal':None,
                        f'{channel}_during_outage':None, f'{channel}_observed':None,
                        f'{channel}_matched_reference':None})
    out['observed_after_onset_min'] = DAY-onset
    out['outlet_blind_minutes_or_lower_bound'] = out['outlet_delay_min'] or DAY-onset
    return out


def open_gzip(path):
    return gzip.open(path,'wt',compresslevel=3,newline='')


def write_samples(path, rows, settings=None):
    fields = [*Sample._fields] + (['fault_active'] if settings else [])
    with open_gzip(path) as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        if settings:
            start,duration = settings
            writer.writerows((*row,int(start < row.minute <= start+duration)) for row in rows)
        else:
            writer.writerows(rows)


def initialize_pool(prefix):
    global PREFIXES,CHECKPOINTS
    PREFIXES = {condition:(rows,seeds) for condition,rows,seeds in prefix}
    CHECKPOINTS = {name:read_checkpoint(name) for name in CONDITIONS}


def equipment_group(job):
    condition,onset,perturbation = job
    group_id = f'{condition}_t{onset}_{perturbation}'
    path = OUT/'equipment'/group_id
    path.mkdir(parents=True,exist_ok=True)
    checkpoint = CHECKPOINTS[condition]
    controls = controls_for(checkpoint)
    prefix,seeds = PREFIXES[condition]
    seed,effluent = seeds[onset]
    reference = new_twin(checkpoint,seed)
    perturb(reference,perturbation,effluent)
    starting_state = capture(reference)
    matched = list(prefix[:onset])
    for _ in range(DAY-onset):
        reference.step(controls)
        matched.append(read_sample(reference))
    write_samples(path/'companion.csv.gz',matched)
    records = []
    for fault in FAULTS:
        active = new_twin(checkpoint,starting_state)
        changed = effect(controls,fault)
        active_rows,restoration = [],{}
        for minute in range(1,max(DURATIONS)+1):
            active.step(changed)
            active_rows.append(read_sample(active))
            if minute in DURATIONS:
                restoration[minute] = capture(active)
        for duration in DURATIONS:
            rows = list(prefix[:onset]) + active_rows[:duration]
            recovering = new_twin(checkpoint,restoration[duration])
            for _ in range(DAY-onset-duration):
                recovering.step(controls)
                rows.append(read_sample(recovering))
            run_id = f'{group_id}_{fault}_{duration}m'
            location = path/f'{fault}_{duration}m.csv.gz'
            write_samples(location,rows,(onset,duration))
            records.append(dict(
                run_id=run_id, condition=condition, influent=condition.split('_')[0],
                rate_h=checkpoint['ammonia_rate_h'], fault=fault, onset_min=onset,
                duration_min=duration, perturbation=perturbation,
                trace=str(location.relative_to(OUT)), companion=str((path/'companion.csv.gz').relative_to(OUT)),
                **detect_equipment(rows,matched,fault,onset,duration),
            ))
    (path/'records.json').write_text(json.dumps(records,indent=2)+'\n')
    return group_id


def sensor_levels(checkpoint,schedule,bias,path):
    twin = new_twin(checkpoint)
    normal = controls_for(checkpoint)
    rows = []
    for minute in range(1,DAY+1):
        command = normal.inlet_gpm * (1.2 if schedule=='surge' and 180 < minute <= 195 else 1.)
        applied = command/(1+bias)
        twin.step(replace(normal,inlet_gpm=applied))
        rows.append((minute,command,applied,100*twin.volume['lift']/SPEC['lift'].cap,twin.alerts))
    with open_gzip(path) as file:
        writer=csv.writer(file)
        writer.writerow(('minute','commanded_inlet_gpm','engine_inlet_gpm','wet_well_pct','engine_alarms'))
        writer.writerows((t,c,a,y,' | '.join(flags)) for t,c,a,y,flags in rows)
    return rows


def sensor_observations(physical,predicted,noise,mode):
    last,streak,active,count=0.,0,False,0
    delay=None
    pre=0
    active_at_injection=False
    for (minute,command,actual,level,_),(_,_,_,expected,_),draw in zip(physical,predicted,noise):
        if minute==SENSOR_START+1:
            active_at_injection=active
        fault_active = minute>SENSOR_START and mode!='healthy'
        if fault_active and mode=='stuck':
            displayed=last
        else:
            drift = .20*(minute-SENSOR_START) if fault_active and mode=='drift' else 0.
            displayed=min(100.,max(0.,level+draw+drift))
        last=displayed
        residual=displayed-expected
        streak=streak+1 if abs(residual)>2. else 0
        confirmed=streak>=2
        transition=confirmed and not active
        active=confirmed
        if transition:
            count+=1
            if minute<=SENSOR_START:
                pre+=1
            if fault_active and delay is None:
                delay=minute-SENSOR_START
        yield (minute,command,actual,level,expected,draw,displayed,residual,int(fault_active),
               int(active),int(transition)), (delay,pre,count,active_at_injection)


def sensor_group(job):
    condition,schedule = job
    checkpoint = CHECKPOINTS[condition]
    target = OUT/'sensor'/f'{condition}_{schedule}'
    target.mkdir(parents=True,exist_ok=True)
    predicted=sensor_levels(checkpoint,schedule,0.,target/'prediction_twin.csv.gz')
    records=[]
    for bias in BIASES:
        tag=f'{bias:+.2f}'
        physical=sensor_levels(checkpoint,schedule,bias,target/f'physical_{tag}.csv.gz')
        loc=target/f'observations_{tag}.csv.gz'
        with open_gzip(loc) as file:
            writer=csv.writer(file)
            writer.writerow(('run_id','mode','seed','minute','commanded_inlet_gpm','actual_inlet_gpm',
                             'plant_level_pct','expected_level_pct','gaussian_draw_pct','displayed_level_pct',
                             'residual_pct','fault_active','alarm_active','alarm_onset'))
            for seed in SEEDS:
                rng=random.Random(seed)
                noise=[rng.gauss(0.,NOISE_SIGMA) for _ in range(DAY)]
                for mode in MODES:
                    run_id=f'{condition}_{schedule}_{tag}_{mode}_{seed:02}'
                    for raw,stats in sensor_observations(physical,predicted,noise,mode):
                        writer.writerow((run_id,mode,seed,*raw))
                    delay,pre,count,active_at_injection=stats
                    records.append(dict(
                        run_id=run_id,condition=condition,rate_h=checkpoint['ammonia_rate_h'],schedule=schedule,
                        flow_bias=bias,mode=mode,seed=seed,trace=str(loc.relative_to(OUT)),
                        detection_delay_min=delay,pre_fault_alarm_events=pre,alarm_events=count,
                        already_active_at_injection=active_at_injection,
                        false_alarm_run=(count>0) if mode=='healthy' else None,
                        detection_state=('not_applicable' if mode=='healthy' else
                                         'detected' if delay is not None else 'right_censored'),
                        observed_after_onset_min=None if mode=='healthy' else DAY-SENSOR_START,
                    ))
    (target/'records.json').write_text(json.dumps(records,indent=2)+'\n')
    return f'{condition}_{schedule}'


def ammonia_comparison(job):
    condition,scenario=job
    checkpoint=CHECKPOINTS[condition]
    twin=new_twin(checkpoint)
    controls=replace(controls_for(checkpoint), **({'aerobic_ph':6.} if scenario=='ph6' else {'aeration':0.}))
    rows=[]
    for _ in range(DAY):
        twin.step(controls)
        rows.append(read_sample(twin))
    path=OUT/'ammonia_comparisons'/f'{condition}_{scenario}.csv.gz'
    write_samples(path,rows)
    return dict(condition=condition,scenario=scenario,rate_h=checkpoint['ammonia_rate_h'],
                trace=str(path.relative_to(OUT)),**rows[-1]._asdict())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_freeze():
    for line in MANIFEST.read_text().splitlines():
        digest,path=line.split('  ',1)
        if sha(ROOT/path)!=digest:
            raise RuntimeError(f'Frozen input changed: {path}')
    for name in CONDITIONS:
        if read_checkpoint(name)['engine_sha256']!=sha(ROOT/'backend'/'engine.py'):
            raise RuntimeError(f'{name} checkpoint is from a different engine')


def write_records(file, rows):
    with file.open('w', newline='') as target:
        writer = csv.DictWriter(target,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def simulate(workers):
    groups=[(condition,onset,p) for condition in CONDITIONS for onset in STARTS
            for p in (FULL if condition==PRIMARY else REDUCED)]
    assert len(groups)==GROUPS_EXPECTED
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'ammonia_comparisons').mkdir(exist_ok=True)
    # The pool first computes the shared, fault-free prefixes, then each worker
    # restores copies of the correct physical state with its own clock/counters.
    with ProcessPoolExecutor(max_workers=workers) as pool:
        prefixes=list(pool.map(prefix_for,CONDITIONS))
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize_pool,initargs=(prefixes,)) as pool:
        equipment=[pool.submit(equipment_group,job) for job in groups]
        sensor=[pool.submit(sensor_group,job) for job in product(CONDITIONS,SCHEDULES)]
        ammonia=[pool.submit(ammonia_comparison,job) for job in product(CONDITIONS,('ph6','aeration_off'))]
        for index,job in enumerate(equipment,1):
            job.result()
            if index%7==0:
                print(f'{index}/{GROUPS_EXPECTED} equipment groups complete',flush=True)
        for job in sensor:
            job.result()
        comparisons=[job.result() for job in ammonia]
    equipment_rows=[r for p in sorted((OUT/'equipment').glob('*/records.json')) for r in json.loads(p.read_text())]
    sensor_rows=[r for p in sorted((OUT/'sensor').glob('*/records.json')) for r in json.loads(p.read_text())]
    assert len(equipment_rows)==FAULT_RUNS_EXPECTED and len(sensor_rows)==SENSOR_RUNS_EXPECTED
    assert len(comparisons)==16
    for filename,rows in [('equipment_detection.csv',equipment_rows),('sensor_detection.csv',sensor_rows),
                          ('ammonia_comparisons.csv',comparisons)]:
        write_records(OUT/filename,rows)
    print(f'{len(equipment_rows)} equipment and {len(sensor_rows)} sensor records written',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=min(8,os.cpu_count() or 1))
    parser.add_argument('--phase',choices=('all','simulate','report'),default='all')
    args=parser.parse_args()
    check_freeze()
    if args.phase in ('simulate','all'):
        simulate(args.workers)
    if args.phase in ('report','all'):
        from step3_reporting import report
        report(OUT)


if __name__=='__main__':
    main()
