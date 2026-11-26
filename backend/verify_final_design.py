"""Verify adopted v2, alternate ammonia bases, and particulate sensitivities."""

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from engine import (Controls, DESIGN_BASIS_AMMONIA_RATE_H, LEGACY_AMMONIA_RATE_H,
                    ORGANIC_DECAY_MULTIPLIERS, RAW_MUNICIPAL_INFLUENT, STAGE_REACTION_RATES_H)
from probe_solids import SolidsLedger
from probe_wasting import verify_case


OUT = Path(__file__).resolve().parents[1] / 'results' / 'model_v2'
TARGETS = {'cod': 30., 'bod': 5.}
INFLUENTS = ('default', 'municipal')
FRACTION_MULTIPLIERS = (.75, 1.25)
AMMONIA_RATES = {
    'adopted': DESIGN_BASIS_AMMONIA_RATE_H,
    'legacy': LEGACY_AMMONIA_RATE_H,
    'minus20': DESIGN_BASIS_AMMONIA_RATE_H * .8,
    'plus20': DESIGN_BASIS_AMMONIA_RATE_H * 1.2,
}


def run_case(influent, variant, *, fractions=1., ammonia_rate=DESIGN_BASIS_AMMONIA_RATE_H):
    raw = {'stream_type': 'municipal', **RAW_MUNICIPAL_INFLUENT} if influent == 'municipal' else {}
    controls = Controls(dt_s=900, **raw)
    twin = SolidsLedger()
    twin.particulate_multiplier = fractions
    twin.reaction_rates_h = {zone: rates.copy() for zone, rates in STAGE_REACTION_RATES_H.items()}
    twin.reaction_rates_h['aero']['nh4'] = ammonia_rate
    result = verify_case(twin, controls, OUT / f'{influent}_{variant}.csv')
    average_waste_kg_day = result['verification_totals']['waste_tss_kg']  # One 24 h window.
    total_tss = sum(tank['tss'] for tank in twin.mass.values())
    result.update(total_tss_inventory_kg=total_tss, tss_waste_kg_day=average_waste_kg_day,
                  waste_only_srt_days=total_tss/average_waste_kg_day,
                  modeled_tin_mg_l=round(twin.effluent_quality['nh4'] + twin.effluent_quality['no3'], 3),
                  particulate_multiplier=fractions, ammonia_rate_h=ammonia_rate)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=6) as pool:
        seed_jobs = {(name,variant): pool.submit(run_case, name, variant, ammonia_rate=rate)
                     for name in INFLUENTS for variant,rate in AMMONIA_RATES.items()}
        fraction_jobs = [
            pool.submit(run_case, name, f'particulate_{factor:g}x', fractions=factor)
            for name in INFLUENTS for factor in FRACTION_MULTIPLIERS
        ]
        baselines = {name: job.result() for name,job in seed_jobs.items()}
        sensitivity = [job.result() for job in fraction_jobs]
    source_hash = hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest()
    conditions = {f'{name}_{variant}': case for (name,variant),case in baselines.items()}
    output = dict(
        engine_sha256=source_hash, scope='Model v2 verification and sensitivity, before Stage 3 faults',
        conditions=conditions, particulate_sensitivity=sensitivity,
        fixed_organic_targets_mg_l=TARGETS, adopted_multipliers=ORGANIC_DECAY_MULTIPLIERS,
        adopted_stage_rates_h=STAGE_REACTION_RATES_H,
    )
    (OUT/'summary.json').write_text(json.dumps(output, indent=2)+'\n')
    for condition,case in conditions.items():
        (OUT/f'{condition}_verified_state.json').write_text(json.dumps(dict(
            engine_sha256=source_hash, controls=case['controls'],
            ammonia_rate_h=case['ammonia_rate_h'], verified_at_s=case['verified']['time_s'],
            volume_m3=case['final_tank_volumes_m3'], mass_kg=case['final_mass_kg'],
            particulate_mass_kg=case['final_particulate_mass_kg'],
        ), indent=2)+'\n')


if __name__ == '__main__':
    main()
