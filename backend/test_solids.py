import unittest

from engine import Controls, RAW_MUNICIPAL_INFLUENT, Twin
from probe_solids import ParticulateTrial, REFERENCE_PARTICULATE, TRIAL_RETENTION


class SolidsTests(unittest.TestCase):
    def test_permeate_is_measured_before_holding_tank(self):
        twin = Twin()
        sample = twin.step(Controls())
        self.assertNotEqual(sample['permeate_tss_mg_l'], sample['effluent_quality']['tss'])
        flow = sum(twin._flows[f'permeate{i}'] for i in range(1, 5))
        self.assertAlmostEqual(sample['permeate_tss_mg_l'] * flow * .001, twin._permeate_tss_mass_kg)
        self.assertIsNone(twin.step(Controls(permeate_on=False))['permeate_tss_mg_l'])

    def test_trial_retains_only_particulate_organics_like_tss(self):
        twin = ParticulateTrial()
        twin.step(Controls())
        twin.volume['mbr1'] = 1.
        twin.volume['outlet'] = 0.
        for field in ('cod', 'bod'):
            twin.mass['mbr1'][field] = 1.
            twin.part['mbr1'][field] = .5
            twin.mass['outlet'][field] = 0.
            twin.part['outlet'][field] = 0.
        twin.mass['mbr1']['tss'] = 1.
        twin.mass['outlet']['tss'] = 0.
        twin.move('mbr1', 'outlet', .1, 'permeate1', twin.membrane_retention)
        for field in ('cod', 'bod'):
            self.assertAlmostEqual(twin.part['outlet'][field], .05 * (1 - TRIAL_RETENTION))
            self.assertAlmostEqual(twin.mass['outlet'][field], .05 + .05 * (1 - TRIAL_RETENTION))
            self.assertAlmostEqual(twin.part['outlet'][field] + twin.part['mbr1'][field], .5)
        self.assertAlmostEqual(twin.mass['outlet']['tss'], .1 * (1 - TRIAL_RETENTION))

    def test_trial_keeps_mass_balance_with_municipal_influent(self):
        trial = ParticulateTrial()
        controls = Controls(dt_s=900, **RAW_MUNICIPAL_INFLUENT)
        state = trial.step(controls)
        self.assertEqual(trial.splits, REFERENCE_PARTICULATE)
        self.assertAlmostEqual(trial.trace[-1]['mb_tss_residual_kg'], 0., places=9)
        for field in ('cod', 'bod'):
            self.assertAlmostEqual(state['quality_balance_kg'][field], 0., places=9)


if __name__ == '__main__':
    unittest.main()
