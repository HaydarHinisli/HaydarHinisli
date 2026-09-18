import atexit
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# app.config.get_settings() is @lru_cache'd and app.db builds its engine from it at
# module-import time, so whichever test file imports app.db/app.main FIRST fixes the
# database URL for the rest of the pytest session. Setting this here, before pytest
# collects any test module, guarantees every HTTP-level test (via TestClient) and the
# app's own startup (migrations + seed_demo) share one consistent, disposable SQLite
# file instead of accidentally touching a real local replica.db.
_fd, _TEST_DB_PATH = tempfile.mkstemp(prefix='replica_test_', suffix='.db')
os.close(_fd)
os.environ['REPLICA_DATABASE_URL'] = f'sqlite:///{_TEST_DB_PATH}'
os.environ.setdefault('REPLICA_DEMO_MODE', 'true')
os.environ.setdefault('REPLICA_JWT_SECRET', 'test-only-secret-not-for-production')


def _cleanup():
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


atexit.register(_cleanup)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEMO_PASSWORD = 'replica-demo-2026'


@pytest.fixture(scope='session')
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, email: str, password: str = DEMO_PASSWORD) -> str:
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()['access_token']


def auth_headers(client, email: str, password: str = DEMO_PASSWORD) -> dict:
    return {'Authorization': f'Bearer {login(client, email, password)}'}
