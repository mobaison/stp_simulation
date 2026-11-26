"""Run the predeclared nitrate-recycle and organic-decay diagnostics."""

import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from engine import (Controls, DESIGN_BASIS_AMMONIA_RATE_H, GPM, LEGACY_MEMBRANE_RETENTION,
                    LEGACY_WASTING_RATIO, RAW_MUNICIPAL_INFLUENT, STAGE_REACTION_RATES_H,
                    TRAIN_TRANSFER_LIMIT_GPM, permeate_fraction)
from probe_design_basis import run_probe


ARCHIVE = Path(__file__).resolve().parents[1] / 'results' / 'recycle_cod_audit'
OUT = ARCHIVE.with_name('recycle_cod_audit_recheck')
RATIOS = (.30, .60, 1., 1.5, 2., 3.)
INFLUENTS = ('default', 'municipal')
TIN_LIMIT = 10.
TARGETS = {'cod': 30., 'bod': 5.}


def controls_for(influent, ratio):
    municipal = {'stream_type': 'municipal', **RAW_MUNICIPAL_INFLUENT}
    controls = Controls(dt_s=300, nrcy_ratio=ratio, wasting_ratio=LEGACY_WASTING_RATIO,
                        **(municipal if influent == 'municipal' else {}))
    controls.permeate_gpm = (
        (controls.inlet_gpm - 4 * TRAIN_TRANSFER_LIMIT_GPM * controls.wasting_ratio)
        / permeate_fraction(controls.fouling, controls.air_scour)
    )
    return controls


def run_recycle(influent, ratio):
    path = OUT / f'recycle_{influent}_{ratio:.2f}.csv'
    case = run_probe(DESIGN_BASIS_AMMONIA_RATE_H, controls_for(influent, ratio), path,
                     nrcy_ratio_limit=max(RATIOS), allow_nonconvergence=True, legacy_bulk=True)
    case.update(influent=influent, nrcy_ratio=ratio)
    print(f'{influent} {ratio:.2f}: {"verified" if case["converged"] else "not verified"}', flush=True)
    return case


def effluent_estimate(case, field, factor, inlet_mg_l, *, passed=None):
    """Solve one of the four identical, well-mixed trains at the observed flows."""
    volume, flow = case['final_tank_volumes_m3'], case['final_flows_m3_h']
    feed, arcy, ras, nrcy = (flow[f'{edge}1'] for edge in ('feed','arcy','ras','nrcy'))
    ana, pre, aero, post = (flow[f'{edge}1'] for edge in ('ana_pre','pre_aero','aero_post','post_mem'))
    permeate, waste = flow['permeate1'], flow['waste1']
    if passed is None:
        passed = 1 - LEGACY_MEMBRANE_RETENTION[field]
    decay = {zone: factor * STAGE_REACTION_RATES_H[zone][field] * volume[f'{zone}1']
             for zone in ('ana','pre','aero','post')}
    # Cm = membrane_per_aerobic * C_aero. Substitute into the soluble/total
    # constituent balances through anaerobic, pre-anoxic and aerobic stages.
    membrane_per_aerobic = (
        (aero / (post + decay['post'])) * post / (arcy + ras + waste + passed * permeate)
    )
    anaerobic_to_pre = ana / (ana + decay['ana'])
    pre_to_aerobic = pre / (pre + decay['pre'])
    external_mass_in = pre_to_aerobic * anaerobic_to_pre * feed * inlet_mg_l
    recycled_per_aerobic = (
        pre_to_aerobic * (anaerobic_to_pre * arcy * membrane_per_aerobic + nrcy)
        + ras * membrane_per_aerobic
    )
    aerobic_concentration = external_mass_in / (aero + nrcy + decay['aero'] - recycled_per_aerobic)
    return passed * membrane_per_aerobic * aerobic_concentration


def factor_for_target(case, field, target_mg_l):
    inlet = RAW_MUNICIPAL_INFLUENT[f'inlet_{field}']
    lo, hi = 1., 100.
    if not effluent_estimate(case, field, hi, inlet) < target_mg_l < effluent_estimate(case, field, lo, inlet):
        raise RuntimeError(f'Design target for {field} not bracketed')
    for _ in range(60):
        mid = (lo + hi) / 2
        if effluent_estimate(case, field, mid, inlet) > target_mg_l:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def passes(case):
    step = case['final_step']
    return (case['converged'] and not case['any_alarms'] and step['rejected_m3'] == 0
            and step['modeled_tin_mg_l'] <= TIN_LIMIT)


def write_sweep(path, cases):
    rows = []
    for case in cases:
        hour, step = case['final_hour'], case['final_step']
        rows.append({
            'influent': case['influent'], 'nrcy_ratio_request': case['nrcy_ratio'],
            'actual_nrcy_over_admitted_inflow': (
                hour['nitrate_recycle_m3'] / hour['admitted_m3'] if hour['admitted_m3'] else None
            ),
            'admitted_gpm': hour['admitted_m3'] / (GPM * 3600),
            'recycled_gpm': hour['nitrate_recycle_m3'] / (GPM * 3600),
            'verified': case['converged'], 'endpoint_hour': step['time_s']/3600,
            **{key: step[key] for key in ('nh4_mg_l','no3_mg_l','modeled_tin_mg_l','rejected_m3','recycle_power_kw')},
            'nominal_nrcy_power_kw': 3 * case['nrcy_ratio'],
            'denitrified_kg_n_h': hour['denitrified_kg_n'], 'peak_tank_pct': case['peak_tank_pct'],
            'alarms_observed': ' | '.join(case['any_alarms']),
            'final_alarms': step['alarms'], 'passes_rule': passes(case),
        })
    with path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = ARCHIVE/'protocol.md'
    protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(run_recycle, influent, ratio) for ratio in RATIOS for influent in INFLUENTS]
        cases = [job.result() for job in jobs]
    write_sweep(OUT/'recycle_summary.csv', cases)
    recommended = next((ratio for ratio in RATIOS
                        if all(passes(case) for case in cases if case['nrcy_ratio']==ratio)), None)
    (OUT/'recycle_summary.json').write_text(json.dumps(dict(
        protocol_sha256=protocol_hash, selection_both_influents=recommended, cases=cases,
    ), indent=2) + '\n')

    municipal = next(case for case in cases if case['influent']=='municipal' and case['nrcy_ratio']==.30)
    if not municipal['converged']:
        raise RuntimeError('Municipal baseline must verify before an organic-rate proposal')
    factors = {field: factor_for_target(municipal, field, target) for field,target in TARGETS.items()}
    proposed_rates = {
        zone: {field: rate * factors[field] for field,rate in rates.items() if field in factors}
        for zone,rates in STAGE_REACTION_RATES_H.items()
    }
    trial = run_probe(DESIGN_BASIS_AMMONIA_RATE_H, controls_for('municipal', .30),
                      OUT/'organic_decay_trial.csv', cod_factor=factors['cod'], bod_factor=factors['bod'],
                      require_bod_stability=True, legacy_bulk=True)
    approx = {field: effluent_estimate(municipal, field, 1., RAW_MUNICIPAL_INFLUENT[f'inlet_{field}'])
              for field in TARGETS}
    v_aero = sum(municipal['final_tank_volumes_m3'][f'aero{i}'] for i in range(1,5))
    f = municipal['final_flows_m3_h']
    (OUT/'organic_decay_summary.json').write_text(json.dumps(dict(
        protocol_sha256=protocol_hash, targets_mg_l=TARGETS, baseline_mixed_tank_estimate_mg_l=approx,
        multipliers=factors, proposed_rates_h=proposed_rates, baseline=municipal, trial=trial,
        aerobic_volume_m3=v_aero,
        aerobic_single_pass_h=v_aero/sum(f[f'{edge}{i}'] for i in range(1,5) for edge in ('aero_post','nrcy')),
        aerobic_volume_over_admitted_flow_h=v_aero/(municipal['final_step']['admitted_m3']*12),
        membrane_retention=LEGACY_MEMBRANE_RETENTION,
    ),indent=2) + '\n')
    print(f'Diagnostic results written to {OUT}')


if __name__ == '__main__':
    main()
