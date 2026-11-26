import unittest
from collections import defaultdict

from engine import (Controls, DESIGN_BASIS_AMMONIA_RATE_H, LEGACY_AMMONIA_RATE_H,
                    LEGACY_MEMBRANE_RETENTION, Twin)
from probe_design_basis import DesignProbe


class DesignBasisTests(unittest.TestCase):
    def test_probe_scales_only_nitrification(self):
        baseline, trial = DesignProbe(LEGACY_AMMONIA_RATE_H), Twin()
        for plant in (baseline, trial):
            plant._conversion = 0.
            plant._removed = defaultdict(float)
        baseline.process('aero1', .1, 1., 1.)
        trial.process('aero1', .1, 1., 1.)
        self.assertGreater(trial._conversion, baseline._conversion)
        self.assertEqual(trial.mass['aero1']['cod'], baseline.mass['aero1']['cod'])
        self.assertEqual(trial.mass['aero1']['bod'], baseline.mass['aero1']['bod'])

        baseline.step(Controls())
        trial.step(Controls())
        self.assertAlmostEqual(baseline.trace[-1]['tin_balance_kg_n'], 0., places=9)
        self.assertGreater(baseline.trace[-1]['denitrified_kg_n'], 0.)

    def test_reference_probe_reproduces_existing_engine(self):
        baseline, probe = Twin(), DesignProbe(DESIGN_BASIS_AMMONIA_RATE_H)
        for _ in range(3):
            self.assertEqual(baseline.step(Controls()), probe.step(Controls()))

    def test_organic_influent_is_uncoupled_from_inorganic_nitrogen(self):
        original, higher_carbon = Twin(), Twin()
        for _ in range(15):
            a = original.step(Controls(dt_s=300))
            b = higher_carbon.step(Controls(dt_s=300, inlet_cod=500., inlet_bod=200.))
            for field in ('nh4', 'no3'):
                self.assertEqual(a['effluent_quality'][field], b['effluent_quality'][field])
        self.assertNotEqual(a['effluent_quality']['cod'], b['effluent_quality']['cod'])

    def test_membrane_retains_bulk_cod_and_tss_independently(self):
        twin = Twin()
        twin.track_particulates = False
        twin.step(Controls())
        twin.volume['mbr1'] = 1.
        twin.volume['outlet'] = 0.
        for field in ('cod', 'tss'):
            twin.mass['mbr1'][field] = 1.
            twin.mass['outlet'][field] = 0.
        self.assertEqual(twin.move('mbr1', 'outlet', .1, 'permeate1', LEGACY_MEMBRANE_RETENTION), .1)
        self.assertAlmostEqual(twin.mass['outlet']['cod'], .082)
        self.assertAlmostEqual(twin.mass['outlet']['tss'], .001)
        for field in ('cod', 'tss'):
            self.assertAlmostEqual(twin.mass['outlet'][field] + twin.mass['mbr1'][field], 1.)

    def test_high_recycle_request_is_diagnostic_only(self):
        high_recycle = Controls(nrcy_ratio=1.5)
        with self.assertRaisesRegex(ValueError, 'Nitrate recycle'):
            Twin().step(high_recycle)
        probe = DesignProbe(DESIGN_BASIS_AMMONIA_RATE_H, nrcy_ratio_limit=3.)
        self.assertGreater(probe.step(high_recycle)['flows_gpm']['nrcy1'], 0.)


if __name__ == '__main__':
    unittest.main()
