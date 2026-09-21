"""docs/DECISIONS.md ADR-057: a REAL browser, driven end-to-end against a REAL
running server (real sockets, real `/api/auth/login`, real `/ws/live/{call_id}`
handshake — no ASGI TestClient shortcut), proving the actual bug the operator
hit and its fix: login -> a genuine JWT -> open /live/{call_id} -> paste the
token -> click Verbinden -> the browser really reaches the authenticated
'Bereit' state, including for a token copy-pasted with an accidental
`Bearer ` prefix or stray whitespace (the confirmed root cause), and that an
actually-invalid token now shows a clear, terminal "Authentifizierung
fehlgeschlagen" state instead of reconnecting forever with the same rejected
token.

This project has no other browser-level test and does not want a hard
dependency on Node+Playwright for `pytest -q` to pass (most machines running
this suite, including the operator's own, will not have it installed) — so
this file skips cleanly, not red, whenever that tooling is unavailable. Where
it IS available (this session verified it end-to-end), it is a real
regression guard for the actual class of bug this ADR fixes; where it is
not, tests/test_live_suggestions_ws.py's ASGI-level token-normalization tests
and tests/test_seller_frontend_structure.py's client-code assertions still
cover the same fix at the unit level.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
DRIVER_SCRIPT = Path(__file__).resolve().parent / 'e2e_live_ws_auth.js'
DEMO_EMAIL = 'admin@replica-pilot.example'
DEMO_PASSWORD = 'replica-demo-2026'


def _npm_global_node_modules() -> str | None:
    try:
        r = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    path = r.stdout.strip()
    return path or None


def _node_env() -> dict | None:
    """Returns an env dict with NODE_PATH set if `node` + the `playwright`
    package are both available, else None (meaning: skip this whole file)."""
    if shutil.which('node') is None:
        return None
    env = os.environ.copy()
    global_modules = _npm_global_node_modules()
    if global_modules:
        env['NODE_PATH'] = global_modules
    check = subprocess.run(
        ['node', '-e', "require.resolve('playwright')"],
        capture_output=True, text=True, env=env,
    )
    if check.returncode != 0:
        return None
    return env


_NODE_ENV = _node_env()
pytestmark = pytest.mark.skipif(
    _NODE_ENV is None,
    reason='Node.js + the playwright npm package are not available in this environment',
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope='module')
def live_server():
    port = _free_port()
    base_url = f'http://127.0.0.1:{port}'
    fd, db_path = tempfile.mkstemp(prefix='replica_e2e_', suffix='.db')
    os.close(fd)
    env = os.environ.copy()
    env['REPLICA_DATABASE_URL'] = f'sqlite:///{db_path}'
    env['REPLICA_DEMO_MODE'] = 'true'
    env['REPLICA_JWT_SECRET'] = 'e2e-test-secret-not-for-production'
    env['REPLICA_ENV'] = 'local'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            try:
                if httpx.get(f'{base_url}/api/health', timeout=1).status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                break
            time.sleep(0.3)
        if not ready:
            output = proc.stdout.read() if proc.stdout else ''
            proc.kill()
            pytest.fail(f'live e2e server never became healthy. Output:\n{output}')
        yield base_url
    finally:
        proc.kill()
        proc.wait(timeout=10)
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture(scope='module')
def call_and_token(live_server):
    token = httpx.post(
        f'{live_server}/api/auth/login', json={'email': DEMO_EMAIL, 'password': DEMO_PASSWORD}, timeout=10,
    ).raise_for_status().json()['access_token']
    call_id = httpx.post(
        f'{live_server}/api/calls',
        headers={'Authorization': f'Bearer {token}'},
        json={'seller_id': 1, 'prospect_company': 'E2E GmbH', 'prospect_type': 'b2b'},
        timeout=10,
    ).raise_for_status().json()['id']
    return call_id, token


def _run_browser_cases(live_server, call_id, token) -> dict:
    result = subprocess.run(
        ['node', str(DRIVER_SCRIPT), live_server, str(call_id), token],
        capture_output=True, text=True, env=_NODE_ENV, timeout=60,
    )
    assert result.returncode == 0, f'driver script crashed: stdout={result.stdout!r} stderr={result.stderr!r}'
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        pytest.fail(f'driver script produced no parseable JSON: stdout={result.stdout!r} stderr={result.stderr!r}')


def test_real_browser_reaches_authenticated_state_including_for_the_confirmed_mistake(live_server, call_and_token):
    """Login -> real JWT -> /live/{call_id} -> paste token -> Verbinden ->
    real WS auth succeeds — for a clean token AND for the two real-world
    copy-paste mistakes (Bearer-prefixed, whitespace-wrapped) that this ADR's
    root-cause investigation confirmed used to fail indistinguishably from a
    genuinely expired token. An actually-invalid token must now show a
    terminal, actionable error instead of looping forever."""
    call_id, token = call_and_token
    data = _run_browser_cases(live_server, call_id, token)
    if data.get('error') == 'browser_launch_failed':
        pytest.skip(f"Playwright's Chromium is not installed in this environment: {data.get('message')}")
    assert 'error' not in data, data

    clean = data['cases']['clean']
    assert clean['statusText'] and 'Bereit' in clean['statusText'], clean
    assert clean['connectCardHidden'] is True

    bearer = data['cases']['bearerPrefixed']
    assert bearer['statusText'] and 'Bereit' in bearer['statusText'], bearer
    assert bearer['connectCardHidden'] is True

    whitespace = data['cases']['whitespaceWrapped']
    assert whitespace['statusText'] and 'Bereit' in whitespace['statusText'], whitespace
    assert whitespace['connectCardHidden'] is True

    invalid = data['cases']['invalid']
    assert invalid['statusText'] and 'Authentifizierung fehlgeschlagen' in invalid['statusText'], invalid
    assert invalid['connectCardHidden'] is False
