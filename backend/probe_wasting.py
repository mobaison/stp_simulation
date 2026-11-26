"""Test calculated solids seeding and unadopted, hydraulically balanced wasting."""

import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

from engine import (Controls, GPM, LEGACY_WASTING_RATIO, MGD_GPM, RAW_MUNICIPAL_INFLUENT,
                    TRAIN_TRANSFER_LIMIT_GPM, Twin, permeate_fraction)
from probe_solids import ParticulateTrial, TRIAL_RETENTION
from warmup import SOLIDS_LOAD_TOLERANCE, prepare_initial_state


OUT = Path(__file__).resolve().parents[1] / 'results' / 'wasting_diagnostic_recheck'
TARGET_MLSS_MG_L = 10_000.
SEED_STEP_S = 5.


def wasting_controls(original: Controls) -> Controls:
    passage = 1. - TRIAL_RETENTION
    raw_tss = RAW_MUNICIPAL_INFLUENT['inlet_tss']
    # Qin Cin = Cmix (Qwaste + passage * Qpermeate), with Qpermeate = Qin - Qwaste.
    waste_gpm = original.inlet_gpm * (raw_tss/TARGET_MLSS_MG_L - passage) / (1. - passage)
    request_gpm = (original.inlet_gpm-waste_gpm) / permeate_fraction(original.fouling, original.air_scour)
    if not 0 < request_gpm <= 3.1 * MGD_GPM:
        raise ValueError('Calculated permeate request is outside the production flow cap')
    return replace(original, wasting_ratio=waste_gpm / (4 * TRAIN_TRANSFER_LIMIT_GPM), permeate_gpm=request_gpm)


def solve_linear(matrix, rhs):
    rows = [row.copy() + [value] for row, value in zip(matrix, rhs)]
    size = len(rows)
    for column in range(size):
        pivot = max(range(column, size), key=lambda i: abs(rows[i][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        if abs(scale) < 1e-13:
            raise RuntimeError('TSS transfer map has no unique equilibrium')
        rows[column] = [v / scale for v in rows[column]]
        for i, row in enumerate(rows):
            if i != column and row[column]:
                weight = row[column]
                rows[i] = [v - weight*w for v,w in zip(row,rows[column])]
    return [row[-1] for row in rows]


def seed_solids(twin: ParticulateTrial, controls: Controls):
    # At settled water volumes the five-second transfer sequence is an affine
    # map in the conservative TSS masses. Capture the actual ordered transfers.
    recorder = Twin()
    recorder.volume = twin.volume.copy()
    recorder.mass = {key: mass.copy() for key, mass in twin.mass.items()}
    recorder.membrane_retention = twin.membrane_retention
    recorder.track_particulates = False  # This map captures water routing and TSS only.
    keys = list(twin.volume)
    index = {key:i for i,key in enumerate(keys)}
    transfers = []
    move = recorder.move

    def record_move(src, dst, amount, name, retain=None):
        before_m3 = recorder.volume[src]
        actual_m3 = move(src, dst, amount, name, retain)
        if actual_m3:
            share = actual_m3 / before_m3 * (1. - (retain or {}).get('tss', 0.))
            transfers.append((index[src], index[dst] if dst is not None else None, share))
        return actual_m3

    recorder.move = record_move
    recorded = recorder.step(replace(controls, dt_s=SEED_STEP_S))
    if recorded['alerts'] or recorder.rejected > 1e-9:
        raise RuntimeError('Cannot seed solids in a hydraulic fault')
    if max(abs(recorder.volume[key]-twin.volume[key]) for key in keys) > 1e-7:
        raise RuntimeError('Water levels have not settled sufficiently to seed solids')
    admitted = recorder._flows['inlet'] * controls.inlet_tss * .001
    size = len(keys)

    def advance(mass, load):
        state = mass.copy()
        state[index['lift']] += load
        for src, dst, share in transfers:
            moved = state[src] * share
            state[src] -= moved
            if dst is not None:
                state[dst] += moved
        return state

    columns = [advance([float(i == j) for i in range(size)], 0.) for j in range(size)]
    matrix = [[float(i == j) - columns[j][i] for j in range(size)] for i in range(size)]
    seed = solve_linear(matrix, advance([0.] * size, admitted))
    residual = max(abs(a-b) for a,b in zip(seed, advance(seed, admitted)))
    if residual > 1e-8 or min(seed) < -1e-8:
        raise RuntimeError('Computed TSS seed is not a nonnegative equilibrium')
    before_kg = sum(mass['tss'] for key, mass in twin.mass.items() if key != 'outlet')
    for key, mass in zip(keys, seed):
        twin.mass[key]['tss'] = max(0., mass)
    seeded_kg = sum(mass['tss'] for key, mass in twin.mass.items() if key != 'outlet')
    # Record the discontinuous initialization separately from the process ledger.
    return dict(time_s=twin.elapsed, preseed_in_process_kg=before_kg, seeded_in_process_kg=seeded_kg,
                seed_tss_by_tank_kg=dict(zip(keys, seed)), fixed_point_max_residual_kg=residual)


def verification_totals(trace, candidate_s):
    rows = [r for r in trace if r['time_s'] > candidate_s]
    totals = {key: sum(r[key] for r in rows) for key in (
        'influent_tss_kg','waste_tss_kg','permeate_tss_kg','in_process_inventory_change_tss_kg','mb_tss_residual_kg',
        'admitted_m3','permeate_m3','waste_m3','discharged_m3',
    )}
    totals['absolute_inventory_change_over_influent_percent'] = (
        100 * abs(totals['in_process_inventory_change_tss_kg']) / totals['influent_tss_kg']
    )
    totals['water_residual_m3'] = totals['admitted_m3'] - totals['waste_m3'] - totals['permeate_m3']
    return totals


def run_case(influent, trial_waste):
    raw = {'stream_type':'municipal', **RAW_MUNICIPAL_INFLUENT} if influent == 'municipal' else {}
    base = Controls(dt_s=900, **raw)
    legacy_waste_gpm = 4 * TRAIN_TRANSFER_LIMIT_GPM * LEGACY_WASTING_RATIO
    base = replace(base, wasting_ratio=LEGACY_WASTING_RATIO,
                   permeate_gpm=(base.inlet_gpm-legacy_waste_gpm)/permeate_fraction(base.fouling, base.air_scour))
    controls = wasting_controls(base) if trial_waste else base
    label = f'{influent}_{"higher_waste" if trial_waste else "original_waste"}'
    return verify_case(ParticulateTrial(), controls, OUT/(label+'.csv'))


def verify_case(twin, controls, trace_path):
    label = trace_path.stem
    prepare_initial_state(controls, max_hours=168, require_solids_stability=False, twin_factory=lambda: twin)
    seed_event = seed_solids(twin, controls)
    result = prepare_initial_state(controls, max_hours=168, twin_factory=lambda: twin)
    totals = verification_totals(twin.trace, result.candidate.time_s)
    if abs(totals['water_residual_m3']) > 1e-6 or abs(totals['mb_tss_residual_kg']) > 1e-6:
        raise RuntimeError(f'Water or TSS ledger did not close for {label}')
    if totals['absolute_inventory_change_over_influent_percent'] >= 100 * SOLIDS_LOAD_TOLERANCE:
        raise RuntimeError(f'24-hour solids loading check failed for {label}')
    actual_gpm = {key.removesuffix('_m3'): totals[key]/(24 * 3600 * GPM)
                  for key in ('admitted_m3', 'permeate_m3', 'waste_m3', 'discharged_m3')}
    with trace_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['phase', *twin.trace[0]])
        writer.writeheader()
        for row in twin.trace:
            writer.writerow({'phase':'preseed' if row['time_s'] <= seed_event['time_s'] else 'seeded', **row})
    print(f'{label}: verified; membrane TSS {twin.trace[-1]["membrane_tss_mg_l"]:.3f} mg/L', flush=True)
    return dict(case=label, controls=asdict(controls), seed=seed_event,
                candidate=asdict(result.candidate), verified=asdict(result.verified),
                final_step=twin.trace[-1], verification_totals=totals, mean_flow_gpm=actual_gpm,
                final_membrane_tss_each_mg_l=list(result.verified.membrane_tss_mg_l),
                particulate_assumptions=twin.splits,
                final_tank_volumes_m3=twin.volume,
                final_flows_m3_h={edge: vol * 3600 / controls.dt_s for edge, vol in twin._flows.items()},
                final_mass_kg=twin.mass, final_particulate_mass_kg=twin.part)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(run_case, name, trial) for name in ('default','municipal') for trial in (False,True)]
        cases = [job.result() for job in jobs]
    evidence = dict(
        status='Diagnostic only. Trial retention and wasting are outside production.',
        declared_municipal_mlss_target_mg_l=TARGET_MLSS_MG_L, tss_retention=TRIAL_RETENTION,
        engine_sha256=hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest(),
        cases=cases,
    )
    (OUT/'summary.json').write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
