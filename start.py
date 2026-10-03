#!/usr/bin/env python3
"""One-click launcher for a trusted collaborator's private cloud configuration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def configuration():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    values.update(os.environ)
    return values


def check_configuration(values):
    required = ('SUPABASE_DATABASE_URL', 'SUPABASE_URL')
    missing = [key for key in required if not values.get(key)]
    if not (values.get('SUPABASE_SECRET_KEY') or values.get('SUPABASE_SERVICE_ROLE_KEY')):
        missing.append('SUPABASE_SECRET_KEY')
    if missing:
        raise ValueError('Place the private .env supplied by the project owner next to start.py. Missing: ' + ', '.join(missing))
    checked = [values[key] for key in required]
    if values.get('CAMPUS_ADMIN_PASSWORD'):
        checked.append(values['CAMPUS_ADMIN_PASSWORD'])
    checked.append(values.get('SUPABASE_SECRET_KEY') or values.get('SUPABASE_SERVICE_ROLE_KEY'))
    if any(marker in value.lower() for value in checked for marker in ('replace_me', 'replace_with_', 'your-project', 'your_database_password', 'your_session_pooler', '<your', '[your')):
        raise ValueError('The configuration still contains examples. Ask the owner for a completed private .env.')
    if values.get('CAMPUS_DB_BACKEND', 'supabase').lower() != 'supabase':
        raise ValueError('Remove the CAMPUS_DB_BACKEND=sqlite override to connect to the shared cloud database.')
    try:
        port = int(values.get('PORT', '8765'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError('PORT must be a number from 1 to 65535.') from None
    return port


def ensure_admin_password(values):
    if values.get('CAMPUS_ADMIN_PASSWORD'):
        return
    path = ROOT / '.launcher-admin-password'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(secrets.token_urlsafe(24) + '\n')
    password = path.read_text(encoding='utf-8').strip()
    if not password:
        raise RuntimeError('The local .launcher-admin-password file is empty. Set CAMPUS_ADMIN_PASSWORD in your private .env.')
    values['CAMPUS_ADMIN_PASSWORD'] = password
    print('Local admin password: open .launcher-admin-password in this project folder to view it privately.', flush=True)


def prepare_python():
    directory = ROOT / '.venv'
    python = directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Preparing the Python environment (first launch)...', flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    probe = subprocess.run(
        [str(python), '-c', "import psycopg, importlib.metadata as m; assert psycopg.__version__ == '3.3.6'; assert m.version('psycopg-binary') == '3.3.6'"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if probe.returncode:
        print('Installing cloud dependencies (internet required)...', flush=True)
        # Do not expose private package-index URLs in installer error output.
        result = subprocess.run(
            [str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-cloud.txt')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode:
            raise RuntimeError('Dependency installation failed. Check internet access; the README has manual installation steps.')
    return python


def launch(python, values, port):
    # Do not open another application's page if the requested port is occupied.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError('The port is already in use. Close your previous Campus Commons window or change PORT in .env.') from None
    values = dict(values, CAMPUS_DB_BACKEND='supabase', PORT=str(port))
    child = subprocess.Popen(
        [str(python), '-u', str(ROOT / 'server.py')], cwd=ROOT, env=values,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Discard potentially sensitive bytes directly without decoding Windows
    # GBK/UTF-8 output or retaining credential-bearing exception text.
    url = f'http://127.0.0.1:{port}/'
    # Local readiness must not go through a user's HTTP proxy.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        print('Connecting to the shared database...', flush=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError('The server could not start. Ask the owner to check cloud credentials, database permissions and network access. See README troubleshooting.')
            try:
                with client.open(url + 'api/bootstrap', timeout=2) as response:
                    data = json.load(response)
                if data.get('organizations') and 'version' in data:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.4)
        else:
            raise RuntimeError('Cloud startup timed out. Check network access and the Supabase project status.')
        print(f'Campus Commons is ready: {url}', flush=True)
        print('Keep this window open. Press Ctrl+C to stop.', flush=True)
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            print('Open the address above in your browser.', flush=True)
        result = child.wait()
        if result:
            raise RuntimeError('The server stopped unexpectedly. See README troubleshooting.')
        return result
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    try:
        if sys.version_info < (3, 10):
            raise RuntimeError('Install Python 3.10 or newer, then double-click the launcher again.')
        values = configuration()
        port = check_configuration(values)
        ensure_admin_password(values)
        return launch(prepare_python(), values, port)
    except KeyboardInterrupt:
        print('\nStopped.')
        return 0
    except (ValueError, RuntimeError) as exc:
        print('Could not start:', exc)
        return 1
    except Exception:
        print('Could not start. Check Python installation, folder permissions and the private .env. No credential details are displayed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
