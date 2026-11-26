import unittest

from engine import Controls, GPM, SPEC, TRAIN_TRANSFER_LIMIT_GPM, Twin, recycle_power_kw


class RecycleEnergyTests(unittest.TestCase):
    def test_disabled_recycle_draws_no_recycle_power(self):
        twin = Twin()
        sample = twin.step(Controls(recycle_on=False))
        self.assertEqual(sample['recycle_power_kw'], 0.)

    def test_recycle_energy_uses_clipped_transfer(self):
        twin = Twin()
        twin.nrcy_ratio_limit = 3.
        for i in range(1, 5):
            twin.volume[f'pre{i}'] = SPEC[f'pre{i}'].cap
        controls = Controls(dt_s=5., nrcy_ratio=3.)
        sample = twin.step(controls)
        total_m3 = sum(twin._flows[f'{edge}{i}'] for i in range(1, 5) for edge in ('nrcy','arcy','ras'))
        actual_gpm = total_m3 / (GPM * controls.dt_s)
        requested_gpm = 4 * TRAIN_TRANSFER_LIMIT_GPM * (controls.nrcy_ratio + controls.arcy_ratio + controls.ras_ratio)
        self.assertLess(actual_gpm, requested_gpm)
        self.assertAlmostEqual(sample['recycle_power_kw'], recycle_power_kw(actual_gpm))


if __name__ == '__main__':
    unittest.main()
