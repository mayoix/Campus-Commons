"""Restart must not transfer saved plan consent to a different resource."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import server


class PlanRestartTests(unittest.TestCase):
    @contextmanager
    def database(self):
        with tempfile.TemporaryDirectory() as d, patch.multiple(server, DB_BACKEND='sqlite', DB_PATH=Path(d)/'test.sqlite3'):
            server.init_db()
            with server.connect() as db:
                yield db

    def resource(self, db, name):
        return server.create_resource(db, {
            'name': name, 'type': 'equipment', 'capability': 'camera, 4K video',
            'location': 'Campus', 'availability_start': '2030-01-01T00:00:00+00:00',
            'availability_end': '2030-01-10T00:00:00+00:00', 'capacity': 1,
        }, 1)['resource']['id']

    def mission(self, db):
        return server.create_mission(db, {
            'title': 'Camera', 'description': 'Need a camera', 'location': 'Campus',
            'resource_types': ['equipment'], 'start_at': '2030-01-03T10:00:00+00:00',
            'end_at': '2030-01-03T12:00:00+00:00',
        }, 2)['mission']

    def row(self, db, mid):
        return db.execute('SELECT * FROM missions WHERE id=?', (mid,)).fetchone()

    def test_restart_keeps_accepted_resource_and_does_not_book_new_alternative(self):
        with self.database() as db:
            a = self.resource(db, 'Camera A'); self.resource(db, 'Camera B')
            m = self.mission(db)
            server.save_preferences(db, m['id'], {'preferences': ['plan-1']}, 2)
            before = self.row(db, m['id'])
            db.execute("UPDATE resources SET status='offline' WHERE id=?", (a,)); db.commit()
            server.init_db(); server.init_db()
            after = self.row(db, m['id'])
            self.assertEqual(after['plans'], before['plans'])
            self.assertEqual(after['preferences'], before['preferences'])
            server.admin_run_batch(db, force=True)
            self.assertEqual(self.row(db, m['id'])['status'], 'waitlisted')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bookings WHERE mission_id=?', (m['id'],)).fetchone()[0], 0)

    def test_restart_preserves_explicitly_accepted_fallback(self):
        with self.database() as db:
            a = self.resource(db, 'Camera A'); b = self.resource(db, 'Camera B')
            m = self.mission(db)
            server.save_preferences(db, m['id'], {'preferences': ['plan-1', 'plan-2']}, 2)
            db.execute("UPDATE resources SET status='offline' WHERE id=?", (a,)); db.commit()
            server.init_db(); server.admin_run_batch(db, force=True)
            row = self.row(db, m['id'])
            self.assertEqual(row['allocated_plan_id'], 'plan-2')
            self.assertEqual(db.execute('SELECT resource_id FROM bookings WHERE mission_id=?', (m['id'],)).fetchone()[0], b)

    def test_recovered_options_cannot_allocate_until_requester_confirms(self):
        with self.database() as db:
            m = self.mission(db); self.assertEqual(m['plans'], [])
            self.resource(db, 'New camera')
            server.init_db()
            row = self.row(db, m['id'])
            self.assertEqual(row['replacement_pending'], 1)
            self.assertEqual(server.loads(row['preferences'], []), [])
            server.admin_run_batch(db, force=True)
            self.assertEqual(self.row(db, m['id'])['status'], 'open')
            server.save_preferences(db, m['id'], {'preferences': ['plan-1']}, 2)
            server.admin_run_batch(db, force=True)
            self.assertEqual(self.row(db, m['id'])['status'], 'allocated')


if __name__ == '__main__':
    unittest.main()
