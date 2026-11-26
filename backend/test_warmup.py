import unittest
from collections import deque
from dataclasses import replace

from engine import Controls, MGD_GPM, permeate_fraction, TRAIN_TRANSFER_LIMIT_GPM, EQ_DIVERSION_BASIS_GPM
from warmup import WarmupSample, VERIFICATION_S, _solids_inventory_closed, _stable, prepare_initial_state


class WarmupTests(unittest.TestCase):
    def test_setpoints_match_nominal_water_balance(self):
        controls = Controls()
        self.assertLess(controls.permeate_gpm, 3.1 * MGD_GPM)
        discharge = controls.permeate_gpm * permeate_fraction(controls.fouling, controls.air_scour)
        waste = 4 * TRAIN_TRANSFER_LIMIT_GPM * controls.wasting_ratio
        self.assertAlmostEqual(discharge + waste, controls.inlet_gpm)
        self.assertAlmostEqual(controls.eq_return_gpm, controls.eq_fraction * EQ_DIVERSION_BASIS_GPM)

    def test_stability_checks_entire_window(self):
        first = WarmupSample(0, 20, 40, 5000, 0, ())
        last = replace(first, time_s=3600, nh4_mg_l=20.05, inventory_m3=5000.5)
        self.assertTrue(_stable(deque((first, last))))
        for middle in (
            replace(first, cod_mg_l=40.25),
            replace(first, nh4_mg_l=None),
            replace(first, alarms=('High level',)),
        ):
            self.assertFalse(_stable(deque((first, middle, last))))
        self.assertFalse(_stable((first, replace(last, inventory_m3=5001))))
        self.assertFalse(_stable((first, replace(last, rejected_m3=0.1))))

    def test_non_dividing_reporting_step_rejected(self):
        with self.assertRaisesRegex(ValueError, 'divide'):
            prepare_initial_state(Controls(dt_s=350))

    def test_solids_gate_requires_permeate_and_every_membrane(self):
        first = WarmupSample(0, 2, 40, 5000, 0, (), 3., (1000.,) * 4)
        stable = replace(first, time_s=3600, permeate_tss_mg_l=3.01)
        self.assertTrue(_stable((first, stable), require_solids_stability=True))
        for unstable in (
            replace(stable, permeate_tss_mg_l=3.02),
            replace(stable, permeate_tss_mg_l=None),
            replace(stable, membrane_tss_mg_l=(1000., 1000., 1006., 1000.)),
        ):
            self.assertFalse(_stable((first, unstable), require_solids_stability=True))

    def test_24_hour_solids_inventory_requires_strict_closure(self):
        first = WarmupSample(0, 2, 40, 5000, 0, (), in_process_tss_kg=5000., admitted_tss_kg=100.)
        settled = replace(first, time_s=86400, in_process_tss_kg=5009.9, admitted_tss_kg=1100.)
        self.assertTrue(_solids_inventory_closed(first, settled))
        self.assertFalse(_solids_inventory_closed(first, replace(settled, in_process_tss_kg=5010.)))
        self.assertFalse(_solids_inventory_closed(first, replace(settled, in_process_tss_kg=4990.)))
        no_load = replace(settled, admitted_tss_kg=100., in_process_tss_kg=5000.)
        self.assertTrue(_solids_inventory_closed(first, no_load))
        self.assertFalse(_solids_inventory_closed(first, replace(no_load, in_process_tss_kg=5000.01)))

    def test_default_warm_start_is_verified_and_independent(self):
        controls = Controls(dt_s=300)
        result = prepare_initial_state(controls, max_hours=96, require_solids_stability=False)
        self.assertEqual(result.verified.time_s - result.candidate.time_s, VERIFICATION_S)
        self.assertTrue(_stable((result.candidate, result.verified)))
        first, second = result.new_twin(), result.new_twin()
        self.assertEqual(first.volume, second.volume)
        self.assertEqual(first.mass, second.mass)
        self.assertEqual(first.part, second.part)
        self.assertIsNot(first.part['mbr1'], second.part['mbr1'])
        self.assertEqual(first.elapsed, 0)
        self.assertEqual(first.history, [])
        snapshot = first.step(controls)
        self.assertEqual(snapshot['alerts'], [])
        self.assertAlmostEqual(snapshot['effluent_quality']['nh4'], result.verified.nh4_mg_l, places=2)
        self.assertAlmostEqual(snapshot['effluent_quality']['cod'], result.verified.cod_mg_l, places=2)
        self.assertNotEqual(first.mass, second.mass)


if __name__ == '__main__':
    unittest.main()
