import unittest
from engine import Twin,Controls,SPEC,FIELDS,MGD_GPM
class Tests(unittest.TestCase):
 def test_conservation(self):
  t=Twin()
  for _ in range(12):
   s=t.step(Controls())
   self.assertLess(abs(s['mass_balance_m3']),1e-5)
   for v in FIELDS:self.assertLess(abs(s['quality_balance_kg'][v]),1e-5)
   for k,d in s['tanks'].items():self.assertGreaterEqual(d['pct'],-1e-5);self.assertLessEqual(d['pct'],100.001)
 def test_limits(self):
  t=Twin()
  for _ in range(20):s=t.step(Controls(permeate_gpm=6000))
  self.assertLessEqual(s['flows_gpm'].get('treated_out',0),3.1*MGD_GPM+1)
 def test_off(self):
  s=Twin().step(Controls(lift_on=False))
  self.assertEqual(s['flows_gpm'].get('lift_pumps',0),0)
 def test_balanced_default_trains_and_lift_failure_alarms(self):
  baseline, fault = Twin(), Twin()
  for _ in range(120):
   normal = baseline.step(Controls())
   failure = fault.step(Controls(lift_on=False))
  self.assertEqual(normal['alerts'], [])
  for stage in ('ana', 'pre', 'aero', 'post', 'mbr'):
   levels = {normal['tanks'][f'{stage}{i}']['pct'] for i in range(1, 5)}
   self.assertEqual(len(levels), 1)
  self.assertIn('Facility lift station: HIGH LEVEL', failure['alerts'])
  self.assertIn('Wet well: incoming sewage rejected', failure['alerts'])
  self.assertIn('Lift pump stopped', failure['alerts'])
 def test_reset(self):
  t=Twin();t.step(Controls());self.assertEqual(t.reset()['history'],[])
 def test_membrane(self):
  t=Twin()
  for _ in range(10):s=t.step(Controls())
  self.assertGreater(s['effluent_quality']['tss'],0)
  self.assertLess(s['effluent_quality']['tss'],s['tanks']['mbr1']['quality']['tss'])

 def test_acidic_aerobic_ph_inhibits_nitrification(self):
  baseline, acidic = Twin(), Twin()
  for _ in range(60):
   normal = baseline.step(Controls(aerobic_ph=7.2))
   low_ph = acidic.step(Controls(aerobic_ph=6.0))
  self.assertGreater(low_ph['effluent_quality']['nh4'], normal['effluent_quality']['nh4'])
  self.assertLess(low_ph['effluent_quality']['no3'], normal['effluent_quality']['no3'])
  self.assertEqual(low_ph['flows_gpm']['treated_out'], normal['flows_gpm']['treated_out'])
  self.assertTrue(any('Aerobic pH' in alarm for alarm in low_ph['alerts']))
  for field in FIELDS:
   self.assertAlmostEqual(low_ph['quality_balance_kg'][field], 0)

 def test_discharge_quality_when_holding_tank_drains(self):
  twin = Twin()
  self.assertTrue(all(value is None for value in twin.snapshot()['effluent_quality'].values()))
  # Give the holding tank exactly one cubic metre. Disable membrane inflow
  # so the discharged concentration can be checked against known masses.
  twin.volume['outlet'] = 1.0
  expected = {field: float(i) for i, field in enumerate(FIELDS)}
  twin.mass['outlet'] = {field: value * .001 for field, value in expected.items()}
  controls = Controls(permeate_on=False)
  sample = twin.step(controls)
  self.assertEqual(sample['tanks']['outlet']['volume_m3'], 0)
  self.assertGreater(sample['flows_gpm']['treated_out'], 0)
  self.assertEqual(sample['effluent_quality'], expected)
  self.assertEqual(sample['history'][-1]['cod'], expected['cod'])
  empty = twin.step(controls)
  self.assertEqual(empty['flows_gpm']['treated_out'], 0)
  self.assertTrue(all(value is None for value in empty['effluent_quality'].values()))
  self.assertIsNone(empty['history'][-1]['cod'])
if __name__=='__main__':unittest.main()
