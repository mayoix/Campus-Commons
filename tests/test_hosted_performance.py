"""Hosted adapter correctness and query-count regression checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import server


class HostedPerformanceTests(unittest.TestCase):
    def test_cloud_rows_support_counts_and_named_fields(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'count': 9}
        row = server.CloudCursor(cursor).fetchone()
        self.assertEqual(row[0], 9)
        self.assertEqual(row['count'], 9)
        self.assertEqual(server.scalar(row), 9)

    def test_pool_returns_connections_after_commit_and_rollback(self):
        pool = MagicMock()
        conn = pool.getconn.return_value
        with patch.multiple(server, _CLOUD_POOL=pool, _CLOUD_POOL_DSN='test-dsn', psycopg=MagicMock(), ConnectionPool=MagicMock()):
            with server.CloudConnection('test-dsn') as db:
                db.execute('SELECT ? AS count', (9,))
            conn.execute.assert_called_once_with('SELECT %s AS count', (9,))
            conn.commit.assert_called_once()
            pool.putconn.assert_called_once_with(conn)
            pool.reset_mock(); conn.reset_mock()
            with self.assertRaises(ValueError):
                with server.CloudConnection('test-dsn'):
                    raise ValueError('test')
            conn.rollback.assert_called_once()
            pool.putconn.assert_called_once_with(conn)

    def test_bulk_read_results_match_individual_serializers(self):
        with tempfile.TemporaryDirectory() as d, patch.multiple(server, DB_BACKEND='sqlite', DB_PATH=Path(d)/'test.sqlite3'):
            server.init_db()
            with server.connect() as db:
                resources = db.execute('SELECT * FROM resources').fetchall()
                self.assertEqual(server.resources_with_usage(db, resources), [server.resource_with_usage(db, r) for r in resources])
                missions = db.execute('SELECT * FROM missions').fetchall()
                self.assertEqual(server.missions_for_client(db, missions, detail=True, viewer_org_id=1), [server.row_to_mission(r, db, True, 1) for r in missions])

    def test_bootstrap_query_count_does_not_grow_per_resource_or_mission(self):
        with tempfile.TemporaryDirectory() as d, patch.multiple(server, DB_BACKEND='sqlite', DB_PATH=Path(d)/'test.sqlite3'):
            server.init_db()
            with server.connect() as db:
                queries=[]; db.set_trace_callback(queries.append)
                server.get_bootstrap(db,1); small=len(queries)
                queries.clear()
                for _ in range(40):
                    db.execute("INSERT INTO resources(owner_org_id,name,type,capability,features,availability_start,availability_end,location,capacity,condition,hourly_value,external_hourly_cost,cost_source,verified,status,created_at) SELECT owner_org_id,name,type,capability,features,availability_start,availability_end,location,capacity,condition,hourly_value,external_hourly_cost,cost_source,verified,status,created_at FROM resources ORDER BY id LIMIT 1")
                    db.execute("INSERT INTO missions(requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,replacement_pending,created_at,updated_at) SELECT requester_org_id,title,description,location,start_at,end_at,deadline,status,requirements,plans,preferences,replacement_pending,created_at,updated_at FROM missions WHERE requester_org_id=1 LIMIT 1")
                db.commit();queries.clear()
                server.get_bootstrap(db,1);large=len(queries)
                self.assertEqual(small,large)
                self.assertLessEqual(large,22)
                print(f'Bootstrap queries: {small} before, {large} after 40 extra resources/Missions')
                queries.clear();server.database_version(db)
                self.assertEqual(len(queries),1)


if __name__ == '__main__':
    unittest.main()
