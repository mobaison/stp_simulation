import csv
import io
import tempfile
import unittest
from pathlib import Path

from engine import Controls, Twin
from history import Recorder, csv_lines


class RecordingTest(unittest.TestCase):
    def test_long_session_restart_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db'
            rec = Recorder(path)
            sim = Twin()
            for i in range(365):
                controls = Controls(lift_on=i % 3 != 0)
                rec.append(sim.step(controls), vars(controls))
            self.assertFalse(rec.sessions())
            restarted = Recorder(path)
            run, = restarted.sessions()
            self.assertEqual(run['status'], 'interrupted')
            self.assertEqual(run['total_steps'], 365)
            steps = list(restarted.steps(run['session_id']))
            self.assertEqual(len(steps), 365)
            self.assertEqual(run['total_alerts_triggered'], sum(len(s['new_alerts']) for s in steps))
            rows = list(csv.DictReader(io.StringIO(''.join(csv_lines(iter(steps))))))
            self.assertEqual(len(rows), 365)
            self.assertEqual(float(rows[-1]['energy_kwh']), run['total_energy_kwh'])
            self.assertEqual(run['effluent_basis'], 'discharge')
            self.assertEqual(run['final_effluent'], steps[-1]['snapshot']['effluent_quality'])
            self.assertEqual(float(rows[-1]['cod_mg_L']), run['final_effluent']['cod'])
            legacy_step = steps[-1]
            del legacy_step['snapshot']['effluent_quality']
            legacy_row, = csv.DictReader(io.StringIO(''.join(csv_lines(iter([legacy_step])))))
            self.assertEqual(legacy_row['cod_mg_L'], '')
            self.assertTrue(restarted.delete(run['session_id']))
            self.assertFalse(list(restarted.steps(run['session_id'])))
