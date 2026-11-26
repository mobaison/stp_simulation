"""Evaluate an ammonia design basis without altering the live model."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from engine import (Controls, DESIGN_BASIS_AMMONIA_RATE_H, GPM, LEGACY_AMMONIA_RATE_H,
                    LEGACY_MEMBRANE_RETENTION, RAW_MUNICIPAL_INFLUENT, Twin)
import warmup


TARGET_NH4_MG_L = 1.0
TIN_SCREEN_MG_L = 10.0


class DesignProbe(Twin):
    def __init__(self, ammonia_rate_h, *, nrcy_ratio_limit=1., cod_factor=1., bod_factor=1.,
                 legacy_bulk=False):
        super().__init__()
        self.nrcy_ratio_limit = nrcy_ratio_limit
        if legacy_bulk:
            self.track_particulates = False
            self.membrane_retention = LEGACY_MEMBRANE_RETENTION
        self.reaction_rates_h = {zone: rates.copy() for zone, rates in self.reaction_rates_h.items()}
        self.reaction_rates_h['aero']['nh4'] = ammonia_rate_h
        for rates in self.reaction_rates_h.values():
            rates['cod'] *= cod_factor
            rates['bod'] *= bod_factor
        self.trace = []
        self.anoxic_n_removed = defaultdict(float)
        self.anoxic_cod_removed = defaultdict(float)

    def process(self, stage, dt_h, aeration, nitrification_factor):
        is_anoxic = stage.startswith(('pre', 'post'))
        if is_anoxic:
            nitrate_before = self.mass[stage]['no3']
            cod_before = self.mass[stage]['cod']
        super().process(stage, dt_h, aeration, nitrification_factor)
        if is_anoxic:
            zone = 'pre_anoxic' if stage.startswith('pre') else 'post_anoxic'
            self.anoxic_n_removed[zone] += nitrate_before - self.mass[stage]['no3']
            self.anoxic_cod_removed[zone] += cod_before - self.mass[stage]['cod']

    def step(self, controls):
        self.anoxic_n_removed.clear()
        self.anoxic_cod_removed.clear()
        initial_mass = sum(mass['nh4'] + mass['no3'] for mass in self.mass.values())
        state = super().step(controls)
        eff = state['effluent_quality']
        n_in = self._flows['inlet'] * (controls.inlet_nh4 + controls.inlet_no3) * .001
        n_out = self._effluent_mass['nh4'] + self._effluent_mass['no3']
        n_waste = self._export['nh4'] + self._export['no3'] - n_out
        n_denitrified = sum(self.anoxic_n_removed.values())
        n_storage_change = sum(mass['nh4'] + mass['no3'] for mass in self.mass.values()) - initial_mass
        self.trace.append(dict(
            time_s=state['time_s'], nh4_mg_l=eff['nh4'], no3_mg_l=eff['no3'],
            modeled_tin_mg_l=round(eff['nh4'] + eff['no3'], 3) if eff['nh4'] is not None else None,
            cod_mg_l=eff['cod'], bod_mg_l=eff['bod'], tss_mg_l=eff['tss'], discharge_m3=self._flows['treated_out'],
            admitted_m3=self._flows['inlet'],
            nitrate_recycle_m3=sum(self._flows[f'nrcy{i}'] for i in range(1, 5)),
            highest_tank_pct=max(tank['pct'] for tank in state['tanks'].values()),
            recycle_power_kw=state['recycle_power_kw'], total_energy_kwh=state['energy_kwh'],
            nitrified_kg_n=self._conversion, pre_anoxic_denitrified_kg_n=self.anoxic_n_removed['pre_anoxic'],
            post_anoxic_denitrified_kg_n=self.anoxic_n_removed['post_anoxic'],
            denitrified_kg_n=n_denitrified, modeled_anoxic_cod_loss_kg=sum(self.anoxic_cod_removed.values()),
            influent_tin_kg_n=n_in, effluent_tin_kg_n=n_out, waste_tin_kg_n=n_waste,
            tin_inventory_change_kg_n=n_storage_change,
            tin_balance_kg_n=n_in-n_out-n_waste-n_denitrified-n_storage_change,
            rejected_m3=self.rejected, alarms=' | '.join(state['alerts']),
        ))
        return state


def run_probe(rate_h, controls, path, *, nrcy_ratio_limit=1., cod_factor=1., bod_factor=1.,
              require_bod_stability=False, allow_nonconvergence=False, legacy_bulk=False):
    probe = DesignProbe(rate_h, nrcy_ratio_limit=nrcy_ratio_limit, cod_factor=cod_factor, bod_factor=bod_factor,
                        legacy_bulk=legacy_bulk)
    baseline_stability = warmup._stable

    def stable_with_nitrate(samples, **options):
        if not baseline_stability(samples, **options):
            return False
        rows = [probe.trace[int(s.time_s / controls.dt_s) - 1] for s in samples]
        fields = ('no3_mg_l', 'bod_mg_l') if require_bod_stability else ('no3_mg_l',)
        for field in fields:
            series = [row[field] for row in rows]
            spread = max(series) - min(series)
            if spread and spread >= warmup.QUALITY_TOLERANCE * series[0]:
                return False
        return True

    # The isolated study also requires nitrate stability, because it is an endpoint.
    with patch.object(warmup, 'Twin', return_value=probe), patch.object(warmup, '_stable', stable_with_nitrate):
        try:
            result = warmup.prepare_initial_state(controls, max_hours=168, require_solids_stability=False)
        except warmup.WarmupNotConverged:
            if not allow_nonconvergence:
                raise
            result = None
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(probe.trace[0]))
        writer.writeheader()
        writer.writerows(probe.trace)

    verified = [row for row in probe.trace if result and row['time_s'] >= result.candidate.time_s]
    nitrate = [row['no3_mg_l'] for row in verified]
    if max(abs(row['tin_balance_kg_n']) for row in probe.trace) > 1e-7:
        raise RuntimeError('The modeled inorganic nitrogen ledger failed to close')

    steps_per_hour = int(3600 / controls.dt_s)
    final_hour = probe.trace[-steps_per_hour:]
    totals = {key: sum(row[key] for row in final_hour) for key in (
        'discharge_m3', 'admitted_m3', 'nitrate_recycle_m3', 'nitrified_kg_n', 'pre_anoxic_denitrified_kg_n',
        'post_anoxic_denitrified_kg_n', 'denitrified_kg_n', 'modeled_anoxic_cod_loss_kg',
        'influent_tin_kg_n', 'effluent_tin_kg_n', 'waste_tin_kg_n',
        'tin_inventory_change_kg_n', 'tin_balance_kg_n',
    )}
    alarms = sorted({alarm for row in probe.trace for alarm in row['alarms'].split(' | ') if alarm})
    return dict(rate_h=rate_h, converged=result is not None,
                candidate=asdict(result.candidate) if result else None,
                verified=asdict(result.verified) if result else None,
                verified_nitrate_range_mg_l=[min(nitrate), max(nitrate)] if nitrate else None,
                any_alarms=alarms, peak_tank_pct=max(row['highest_tank_pct'] for row in probe.trace),
                final_step=probe.trace[-1], final_hour=totals, final_tank_volumes_m3=probe.volume,
                final_flows_m3_h={edge: volume * 3600 / controls.dt_s for edge, volume in probe._flows.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--influent', choices=('default', 'municipal'), default='default')
    parser.add_argument('--ammonia-rate', type=float, help='Trial rate in h⁻¹; defaults to the adopted design basis.')
    options = parser.parse_args()
    if options.ammonia_rate is not None and not 0 < options.ammonia_rate < float('inf'):
        parser.error('--ammonia-rate must be positive and finite')
    root = Path(__file__).resolve().parents[1]
    fingerprint = hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest()
    target_rate_h = options.ammonia_rate if options.ammonia_rate is not None else DESIGN_BASIS_AMMONIA_RATE_H
    controls = (Controls(stream_type='municipal', **RAW_MUNICIPAL_INFLUENT)
                if options.influent == 'municipal' else Controls())
    out = root/'results'/'design_basis_probe'/'reproductions'/options.influent
    out.mkdir(parents=True, exist_ok=True)
    baseline = run_probe(LEGACY_AMMONIA_RATE_H, controls, out/'existing_rate.csv')
    proposal = run_probe(target_rate_h, controls, out/'candidate_rate.csv')
    hour = proposal['final_hour']
    additional_n = max(0., hour['effluent_tin_kg_n'] - TIN_SCREEN_MG_L * hour['discharge_m3'] * .001)
    evidence = dict(
        status='Isolated comparison; neither calibration nor field validation',
        engine_sha256=fingerprint, controls=asdict(controls), influent=options.influent,
        default_influent_nh4_target_mg_l=TARGET_NH4_MG_L,
        proposed_rate_h=target_rate_h, baseline=baseline, proposal=proposal,
        screening=dict(
            modeled_tin_screen_mg_l=TIN_SCREEN_MG_L,
            additional_effluent_tin_to_remove_kg_n_h=additional_n,
            stoichiometric_minimum_additional_cod_kg_h=2.86*additional_n,
            current_denitrification_minimum_cod_equivalent_kg_h=2.86*hour['denitrified_kg_n'],
            tin_screen_minimum_cod_equivalent_kg_h=2.86*(additional_n+hour['denitrified_kg_n']),
            upper_bound_denitrification_from_modeled_anoxic_cod_kg_n_h=hour['modeled_anoxic_cod_loss_kg']/2.86,
            candidate_nitrification_oxygen_demand_kg_h=4.57*hour['nitrified_kg_n'],
            candidate_nitrification_alkalinity_demand_as_caco3_kg_h=7.14*hour['nitrified_kg_n'],
            balanced_discharge_gpm=hour['discharge_m3']/(GPM*3600),
        ),
    )
    (out/'summary.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'Design-basis diagnostics written to {out}')


if __name__ == '__main__':
    main()
