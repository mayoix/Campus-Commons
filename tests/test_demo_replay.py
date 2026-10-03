"""Replay reports explain bookings without mutating live business records."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class DemoReplayTests(unittest.TestCase):
    def test_replay_has_consistent_frames_and_keeps_business_data_isolated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'DB_PATH', Path(directory) / 'test.sqlite3'), patch.object(server, 'DB_BACKEND', 'sqlite'):
            server.init_db()
            with server.connect() as db:
                tables = ['organizations', 'resources', 'missions', 'bookings', 'credit_events', 'history_log']
                before = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
                report = server.run_demo(db, {'scenario': 'all'})['report']
                scenarios = {s['key']: s for s in report['scenarios']}
                self.assertEqual(set(scenarios), {'conflict', 'withdrawal', 'replacement', 'preference'})
                for scenario in scenarios.values():
                    self.assertEqual(len(scenario['frames']), len(scenario['timeline']))
                    for frame in scenario['frames']:
                        for link in frame['links']:
                            self.assertLess(link['resource'], len(frame['resources']))
                conflict = scenarios['conflict']['frames']
                self.assertIsNone(conflict[4]['resources'][0]['booked_by'])
                self.assertEqual(conflict[-1]['resources'][0]['booked_by'], 'M-101')
                self.assertEqual(conflict[-1]['missions'][1]['status'], 'Waitlisted')
                replacement = scenarios['replacement']['frames']
                self.assertIsNone(replacement[3]['resources'][1]['booked_by'])
                self.assertEqual(replacement[3]['missions'][0]['status'], 'Awaiting confirmation')
                self.assertEqual(replacement[4]['resources'][1]['booked_by'], 'M-301')
                self.assertIsNone(replacement[4]['resources'][0]['booked_by'])
                preference = scenarios['preference']['frames'][-1]
                self.assertIsNone(preference['resources'][0]['booked_by'])
                self.assertEqual(preference['resources'][1]['booked_by'], 'M-401')
                after = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
                self.assertEqual(before, after)
                saved = json.loads(db.execute('SELECT report FROM demo_runs WHERE id=?', (report['demo_run_id'],)).fetchone()[0])
                self.assertEqual(len(saved['scenarios']), 4)


if __name__ == '__main__':
    unittest.main()
