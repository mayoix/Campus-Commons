"""Offline tests of read-only checks and credential-safe failure reporting."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('check_connection', Path(__file__).resolve().parents[1] / 'scripts/check_connection.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ConnectionCheckTests(unittest.TestCase):
    def run_check(self, *, database_error=None, buckets=None, scheduler=0, backend='supabase', admin='unit-test-private-password'):
        driver = MagicMock()
        db = driver.connect.return_value.__enter__.return_value

        def execute(query):
            result = MagicMock()
            text = str(query)
            if 'COUNT(*)' in text:
                result.fetchone.return_value = (5,)
            elif 'scheduler_enabled' in text:
                result.fetchone.return_value = (scheduler,)
            else:
                result.fetchone.return_value = (1,)
            return result

        db.execute.side_effect = execute
        if database_error:
            driver.connect.side_effect = database_error
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(
            buckets if buckets is not None else [{'id': 'campus-evidence', 'public': False}]
        ).encode())
        output = io.StringIO()
        with patch.multiple(check.server, DB_BACKEND=backend, SUPABASE_DATABASE_URL='postgresql://user:unit-test-secret@db.example/test',
                            SUPABASE_URL='https://project.example', SUPABASE_SECRET_KEY='unit-test-key',
                            SUPABASE_EVIDENCE_BUCKET='campus-evidence', psycopg=driver), \
             patch.dict(os.environ, {'CAMPUS_ADMIN_PASSWORD': admin}), \
             patch.object(check.urllib.request, 'urlopen', return_value=response) as http, \
             contextlib.redirect_stdout(output):
            code = check.main()
        return code, output.getvalue(), driver, db, http

    def test_success_is_read_only_and_verifies_tls(self):
        code, text, driver, db, http = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('Read-only preflight passed', text)
        settings = driver.connect.call_args.kwargs
        self.assertEqual(settings['sslmode'], 'verify-full')
        self.assertIn('default_transaction_read_only=on', settings['options'])
        for call in db.execute.call_args_list:
            self.assertIn('SELECT', str(call.args[0]))
        self.assertEqual(http.call_args.args[0].get_method(), 'GET')

    def test_database_errors_never_expose_credentials(self):
        code, text, *_ = self.run_check(database_error=RuntimeError('unit-test-secret unit-test-key'))
        self.assertEqual(code, 1)
        self.assertNotIn('unit-test-secret', text)
        self.assertNotIn('unit-test-key', text)

    def test_local_backend_cannot_pass_as_cloud(self):
        code, text, driver, *_ = self.run_check(backend='sqlite')
        self.assertEqual(code, 1)
        driver.connect.assert_not_called()

    def test_missing_or_public_bucket_fails(self):
        for buckets in ([], [{'id': 'campus-evidence', 'public': True}]):
            with self.subTest(buckets=buckets):
                self.assertEqual(self.run_check(buckets=buckets)[0], 1)

    def test_automatic_scheduler_prevents_multi_server_readiness(self):
        code, text, *_ = self.run_check(scheduler=1)
        self.assertEqual(code, 1)
        self.assertIn('automatic scheduling', text)

    def test_admin_placeholder_fails(self):
        self.assertEqual(self.run_check(admin='replace_with_a_new_private_admin_password')[0], 1)


if __name__ == '__main__':
    unittest.main()
