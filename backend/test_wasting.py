import unittest
from dataclasses import replace

from engine import Controls, LEGACY_WASTING_RATIO, RAW_MUNICIPAL_INFLUENT, TRAIN_TRANSFER_LIMIT_GPM, permeate_fraction
from probe_solids import TRIAL_RETENTION
from probe_wasting import TARGET_MLSS_MG_L, solve_linear, wasting_controls


class WastingTests(unittest.TestCase):
    def test_calculated_waste_balances_water_and_solids_at_declared_target(self):
        baseline = replace(Controls(), wasting_ratio=LEGACY_WASTING_RATIO)
        controls = wasting_controls(baseline)
        self.assertGreater(controls.wasting_ratio, baseline.wasting_ratio)
        waste = controls.wasting_ratio * 4 * TRAIN_TRANSFER_LIMIT_GPM
        permeate = controls.permeate_gpm * permeate_fraction(controls.fouling, controls.air_scour)
        self.assertAlmostEqual(waste + permeate, controls.inlet_gpm)
        self.assertAlmostEqual(TARGET_MLSS_MG_L * (waste + permeate * (1 - TRIAL_RETENTION)),
                               controls.inlet_gpm * RAW_MUNICIPAL_INFLUENT['inlet_tss'])

    def test_solids_solver_can_pivot(self):
        self.assertEqual(solve_linear([[0., 2.], [1., 3.]], [6., 11.]), [2., 3.])
        with self.assertRaisesRegex(RuntimeError, 'no unique'):
            solve_linear([[1., 2.], [2., 4.]], [1., 2.])


if __name__ == '__main__':
    unittest.main()
