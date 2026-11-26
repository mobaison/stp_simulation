"""Evaluate solids convergence and an unadopted membrane-retention alternative."""

import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from engine import (Controls, DESIGN_TSS_RETENTION, LEGACY_MEMBRANE_RETENTION,
                    LEGACY_WASTING_RATIO, RAW_MUNICIPAL_INFLUENT, REFERENCE_PARTICULATE, Twin,
                    TRAIN_TRANSFER_LIMIT_GPM, permeate_fraction)
from warmup import MAX_WARMUP_HOURS, WarmupNotConverged, prepare_initial_state


OUTPUT = Path(__file__).resolve().parents[1] / 'results' / 'solids_diagnostic_recheck'
TRIAL_RETENTION = DESIGN_TSS_RETENTION


class SolidsLedger(Twin):
    def __init__(self):
        super().__init__()
        self.trace = []

    def step(self, controls):
        in_process_before = sum(m['tss'] for key, m in self.mass.items() if key != 'outlet')
        state = super().step(controls)
        admitted_m3 = self._flows['inlet']
        inventory = sum(m['tss'] for key, m in self.mass.items() if key != 'outlet')
        solids_in = admitted_m3 * controls.inlet_tss * .001
        discharged = self._effluent_mass['tss']
        waste = self._export['tss'] - discharged
        membrane_m3 = sum(self._flows.get(f'permeate{i}', 0.) for i in range(1, 5))
        waste_m3 = sum(self._flows.get(f'waste{i}', 0.) for i in range(1, 5))
        membrane_stock = sum(self.mass[f'mbr{i}']['tss'] for i in range(1, 5))
        membrane_water = sum(self.volume[f'mbr{i}'] for i in range(1, 5))
        self.trace.append(dict(
            time_s=self.elapsed, admitted_m3=admitted_m3, permeate_m3=membrane_m3, waste_m3=waste_m3,
            discharged_m3=self._flows['treated_out'],
            influent_tss_kg=solids_in, waste_tss_kg=waste, permeate_tss_kg=self._permeate_tss_mass_kg,
            discharged_tss_kg=discharged, in_process_inventory_tss_kg=inventory,
            in_process_inventory_change_tss_kg=inventory - in_process_before,
            mb_tss_residual_kg=solids_in-waste-self._permeate_tss_mass_kg-(inventory-in_process_before),
            membrane_tss_mg_l=membrane_stock * 1000 / membrane_water if membrane_water else None,
            permeate_tss_mg_l=state['permeate_tss_mg_l'], effluent_tss_mg_l=state['effluent_quality']['tss'],
            effluent_cod_mg_l=state['effluent_quality']['cod'], effluent_bod_mg_l=state['effluent_quality']['bod'],
            effluent_nh4_mg_l=state['effluent_quality']['nh4'], effluent_no3_mg_l=state['effluent_quality']['no3'],
            rejected_m3=self.rejected, alarms=' | '.join(state['alerts']),
        ))
        return state


class LegacySolidsLedger(SolidsLedger):
    membrane_retention = LEGACY_MEMBRANE_RETENTION
    track_particulates = False


# Keep the diagnostic entry point available for the historical trials.
ParticulateTrial = SolidsLedger


def run_case(influent, trial):
    controls = Controls(dt_s=900, **({'stream_type': 'municipal', **RAW_MUNICIPAL_INFLUENT}
                                     if influent == 'municipal' else {}))
    controls.wasting_ratio = LEGACY_WASTING_RATIO
    controls.permeate_gpm = (
        (controls.inlet_gpm - 4 * TRAIN_TRANSFER_LIMIT_GPM * controls.wasting_ratio)
        / permeate_fraction(controls.fouling, controls.air_scour)
    )
    twin = ParticulateTrial() if trial else LegacySolidsLedger()
    code = f'{influent}_{"retention_trial" if trial else "current"}'
    try:
        result = prepare_initial_state(controls, twin_factory=lambda: twin)
    except WarmupNotConverged:
        result = None
    with (OUTPUT/f'{code}.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(twin.trace[0]))
        writer.writeheader()
        writer.writerows(twin.trace)
    hour = twin.trace[-int(3600 / controls.dt_s):]
    maximum_residual = max(abs(row['mb_tss_residual_kg']) for row in twin.trace)
    if maximum_residual > 1e-7:
        raise RuntimeError(f'TSS balance did not close for {code}')
    totals = {key: sum(row[key] for row in hour) for key in (
        'influent_tss_kg', 'waste_tss_kg', 'permeate_tss_kg', 'discharged_tss_kg',
        'in_process_inventory_change_tss_kg', 'mb_tss_residual_kg',
    )}
    case = dict(
        case=code, input_controls=asdict(controls), is_trial=trial, converged=result is not None,
        notes='Membrane tank TSS is a mixed-liquor solids proxy; biomass is not explicit.',
        candidate=asdict(result.candidate) if result else None, verified=asdict(result.verified) if result else None,
        final_step=twin.trace[-1], final_hour_tss_kg=totals, max_step_tss_residual_kg=maximum_residual,
        particulate_inlet_fractions=twin.splits if trial else None,
        net_tss_removal_permeate_equilibrium_mg_l=(
            (1. - twin.membrane_retention['tss']) * controls.inlet_gpm * controls.inlet_tss
            / (28. + (1. - twin.membrane_retention['tss']) * 1872.)
        ),
    )
    (OUTPUT/f'{code}.json').write_text(json.dumps(case, indent=2) + '\n')
    print(f'{code}: {"verified" if result else "not verified"} by hour {twin.elapsed/3600:.2f}', flush=True)
    return case


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(run_case, influent, trial)
                for influent in ('default', 'municipal') for trial in (False, True)]
        cases = [job.result() for job in jobs]
    (OUTPUT/'summary.json').write_text(json.dumps(dict(
        status='Proposed retention and particulate treatment are isolated diagnostics only.',
        engine_sha256=hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest(),
        warmup_deadline_h=MAX_WARMUP_HOURS, trial_tss_retention=TRIAL_RETENTION,
        reference_particulate=REFERENCE_PARTICULATE, cases=cases,
    ), indent=2) + '\n')


if __name__ == '__main__':
    main()
