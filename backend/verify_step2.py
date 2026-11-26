"""Regenerate the warm-up verification and structural mass-balance audit."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from engine import Controls, GPM, LEGACY_WASTING_RATIO, TRAIN_TRANSFER_LIMIT_GPM, Twin, permeate_fraction
from warmup import prepare_initial_state, WarmStart, WarmupSample


TRACKED = ('nh4', 'cod')


class LedgerTwin(Twin):
    """Instrument transfers and reactions while retaining the engine's calculations."""

    def __init__(self):
        super().__init__()
        self.edge_volumes = defaultdict(float)
        self.edge_masses = defaultdict(float)
        self.reaction_masses = defaultdict(float)

    def move(self, src, dst, amount, name, retain=None):
        before = {field: self.mass[src][field] for field in TRACKED}
        volume = super().move(src, dst, amount, name, retain)
        self.edge_volumes[name] += volume
        for field in TRACKED:
            self.edge_masses[name, field] += before[field] - self.mass[src][field]
        return volume

    def process(self, stage, dt_h, aeration, nitrification_factor):
        before = {field: self.mass[stage][field] for field in TRACKED}
        super().process(stage, dt_h, aeration, nitrification_factor)
        for field in TRACKED:
            self.reaction_masses[stage, field] += before[field] - self.mass[stage][field]


def run_warmup(dt_s):
    return prepare_initial_state(Controls(dt_s=dt_s), max_hours=168, require_solids_stability=False)


def write_trace(path: Path, samples: tuple[WarmupSample, ...] | list[WarmupSample]):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(samples[0])))
        writer.writeheader()
        for sample in samples:
            writer.writerow({**asdict(sample), 'alarms': ' | '.join(sample.alarms)})


def structural_ledger(twin, controls):
    twin.edge_volumes.clear()
    twin.edge_masses.clear()
    twin.reaction_masses.clear()
    beginning_mass = {field: sum(mass[field] for mass in twin.mass.values()) for field in TRACKED}
    admitted_m3 = 0.
    for _ in range(int(3600 / controls.dt_s)):
        twin.step(controls)
        admitted_m3 += twin._flows['inlet']

    waste_edges = [f'waste{i}' for i in range(1, 5)]
    recycles = {
        name: [f'{name}{i}' for i in range(1, 5)]
        for name in ('nrcy', 'arcy', 'ras')
    }
    balances = {}
    for field in TRACKED:
        admitted_kg = admitted_m3 * getattr(controls, f'inlet_{field}') * .001
        treated_kg = twin.edge_masses['treated_out', field]
        wasted_kg = sum(twin.edge_masses[edge, field] for edge in waste_edges)
        reacted_kg = sum(mass for (_, species), mass in twin.reaction_masses.items() if species == field)
        inventory_delta_kg = sum(mass[field] for mass in twin.mass.values()) - beginning_mass[field]
        closure_kg = admitted_kg - treated_kg - wasted_kg - reacted_kg - inventory_delta_kg
        if abs(closure_kg) > 1e-7:
            raise RuntimeError(f'{field} ledger failed to close: {closure_kg} kg')
        balances[field] = dict(admitted_kg=admitted_kg, treated_kg=treated_kg, wasted_kg=wasted_kg,
                               reacted_kg=reacted_kg, inventory_delta_kg=inventory_delta_kg,
                               closure_kg=closure_kg)

    aerobic_m3 = sum(twin.volume[f'aero{i}'] for i in range(1, 5))
    aerobic_nh4_kg = sum(twin.mass[f'aero{i}']['nh4'] for i in range(1, 5))
    aerobic_out_m3_h = sum(twin.edge_volumes[f'{edge}{i}']
                           for i in range(1, 5) for edge in ('aero_post', 'nrcy'))
    with_recycle = {
        name: {
            'flow_gpm': sum(twin.edge_volumes[edge] for edge in edges) / (GPM * 3600),
            'flow_over_influent': sum(twin.edge_volumes[edge] for edge in edges) / admitted_m3,
            'nh4_kg_h': sum(twin.edge_masses[edge, 'nh4'] for edge in edges),
        }
        for name, edges in recycles.items()
    }
    first_order_per_h = balances['nh4']['reacted_kg'] / aerobic_nh4_kg
    effective_contact_h = aerobic_m3 / admitted_m3
    return dict(
        balances=balances, recycles=with_recycle, aerobic_m3=aerobic_m3,
        admitted_gpm=admitted_m3/(GPM*3600),
        treated_gpm=twin.edge_volumes['treated_out']/(GPM*3600),
        waste_gpm=sum(twin.edge_volumes[edge] for edge in waste_edges)/(GPM*3600),
        aerobic_nh4_kg=aerobic_nh4_kg,
        gross_aerobic_outflow_m3_h=aerobic_out_m3_h,
        aerobic_single_pass_h=aerobic_m3/aerobic_out_m3_h,
        aerobic_volume_over_influent_h=effective_contact_h,
        observed_first_order_per_h=first_order_per_h,
        ideal_mixed_tank_nh4_mg_l_by_rate_multiplier={
            str(multiplier): controls.inlet_nh4 / (1 + multiplier * first_order_per_h * effective_contact_h)
            for multiplier in (0.8, 1.0, 1.2)
        },
    )


def percent_difference(a, b):
    return 100 * abs(a-b) / abs(b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'results' / 'step2')
    path = parser.parse_args().output
    path.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2) as pool:
        one = pool.submit(run_warmup, 60)
        five = pool.submit(run_warmup, 300)
        start_60, start_300 = one.result(), five.result()
    for label, start in [('60s', start_60), ('300s', start_300)]:
        write_trace(path / f'warmup_{label}.csv', start.samples)

    # A comparison at the same physical time isolates any reporting-step effect.
    common_s = min(start_60.verified.time_s, start_300.verified.time_s)
    common_s = int(common_s // 300) * 300
    matched = {label: next(sample for sample in start.samples if sample.time_s == common_s)
               for label, start in [('60s', start_60), ('300s', start_300)]}
    matched_diff = {key: percent_difference(getattr(matched['60s'], key), getattr(matched['300s'], key))
                    for key in ('nh4_mg_l', 'cod_mg_l')}
    end_diff = {key: percent_difference(getattr(start_60.verified, key), getattr(start_300.verified, key))
                for key in ('nh4_mg_l', 'cod_mg_l')}
    controls = Controls()
    old_nominal_output = (1900 * permeate_fraction(controls.fouling, controls.air_scour)
                          + 4 * TRAIN_TRANSFER_LIMIT_GPM * LEGACY_WASTING_RATIO)
    seed = start_60.new_twin()
    no_recycle = start_60.new_twin(LedgerTwin)
    no_recycle_controls = Controls(dt_s=300, recycle_on=False)
    recycle_probe = []
    for _ in range(48 * 3600 // 300):
        state = no_recycle.step(no_recycle_controls)
        recycle_probe.append(WarmupSample(
            no_recycle.elapsed, state['effluent_quality']['nh4'], state['effluent_quality']['cod'],
            sum(no_recycle.volume.values()), no_recycle.rejected, tuple(state['alerts']),
        ))
    write_trace(path/'no_recycle_probe.csv', recycle_probe)
    audit = {
        'engine_sha256': hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest(),
        'controls': asdict(controls),
        'legacy_inflow_minus_discharge_and_waste_gpm': controls.inlet_gpm - old_nominal_output,
        'warmup': {
            label: {'candidate': asdict(start.candidate), 'verified': asdict(start.verified)}
            for label, start in [('60s', start_60), ('300s', start_300)]
        },
        'equal_elapsed_comparison': {label: asdict(sample) for label, sample in matched.items()},
        'equal_elapsed_difference_percent': matched_diff,
        'verified_end_difference_percent': end_diff,
        'structural_ledger_60s': structural_ledger(start_60.new_twin(LedgerTwin), controls),
        'no_recycle_diagnostic_300s': {
            'initial_condition': 'Verified 60 s baseline; recycle disabled from time zero',
            'first_alarm': next((asdict(s) for s in recycle_probe if s.alarms), None),
            'state_after_48h': asdict(recycle_probe[-1]),
            'following_hour_ledger': structural_ledger(no_recycle, no_recycle_controls),
        },
    }
    (path/'step2_summary.json').write_text(json.dumps(audit, indent=2) + '\n')
    if max(*matched_diff.values(), *end_diff.values()) > 2:
        raise RuntimeError('Warm-up results differ by more than 2% across reporting steps')
    (path/'initial_state_60s.json').write_text(json.dumps({
        'engine_sha256': audit['engine_sha256'], 'controls': asdict(controls),
        'verified_at_s': start_60.verified.time_s, 'volume_m3': seed.volume, 'mass_kg': seed.mass,
        'particulate_mass_kg': seed.part,
    }, indent=2) + '\n')
    print(f'Step 2 results written to {path}')


if __name__ == '__main__':
    main()
