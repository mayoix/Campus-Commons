import contextlib
import importlib.util
import io
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[1] / 'start.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def values(self):
        return dict(os.environ, SUPABASE_DATABASE_URL='postgresql://user:test-only-password@db.example/app',
                    SUPABASE_URL='https://project.example', SUPABASE_SECRET_KEY='test-only-key',
                    CAMPUS_ADMIN_PASSWORD='test-only-admin', CAMPUS_DB_BACKEND='supabase', PORT='8765')

    def test_private_configuration_loads_with_bom_and_shell_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.dict(os.environ, {'PORT': '8766'}, clear=True):
            (Path(directory) / '.env').write_text('\ufeffSUPABASE_URL="https://project.example"\nPORT=8765\n', encoding='utf8')
            values = launcher.configuration()
            self.assertEqual(values['PORT'], '8766')
            self.assertEqual(values['SUPABASE_URL'], 'https://project.example')

    def test_missing_configuration_prevents_install_or_start(self):
        with patch.object(launcher, 'configuration', return_value={}), patch.object(launcher, 'prepare_python') as prepare, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(), 1)
            prepare.assert_not_called()
            self.assertIn('private .env', output.getvalue())

    def test_invalid_config_never_falls_back_to_sqlite(self):
        for key, value in [('CAMPUS_DB_BACKEND', 'sqlite'), ('PORT', '70000'), ('SUPABASE_SECRET_KEY', 'sb_secret_replace_me')]:
            values = self.values()
            values[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                launcher.check_configuration(values)

    def test_occupied_port_does_not_launch_another_server(self):
        with socket.socket() as listener, patch.object(launcher.subprocess, 'Popen') as popen:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, 'port is already in use'):
                launcher.launch(Path(sys.executable), self.values(), listener.getsockname()[1])
            popen.assert_not_called()

    def test_browser_opens_only_after_child_serves_bootstrap(self):
        # A real local HTTP child exercises readiness/lifecycle, not cloud behavior.
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.object(launcher.webbrowser, 'open', return_value=True) as browser, contextlib.redirect_stdout(io.StringIO()):
            (Path(directory) / 'server.py').write_text('''import os
from http.server import HTTPServer, BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"organizations":[{"id":1}],"version":"test"}'
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
server = HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler)
server.handle_request()
server.server_close()
''')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            self.assertEqual(launcher.launch(Path(sys.executable), self.values(), port), 0)
            browser.assert_called_once_with(f'http://127.0.0.1:{port}/')

    def test_failed_child_does_not_print_its_credentials_or_open_browser(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.object(launcher.webbrowser, 'open') as browser, contextlib.redirect_stdout(io.StringIO()) as output:
            (Path(directory) / 'server.py').write_text('raise RuntimeError("test-only-secret-in-raw-error")')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, 'server could not start'):
                launcher.launch(Path(sys.executable), self.values(), port)
            browser.assert_not_called()
            self.assertNotIn('test-only-secret-in-raw-error', output.getvalue())


if __name__ == '__main__':
    unittest.main()
