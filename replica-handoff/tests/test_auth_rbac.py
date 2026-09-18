"""Auth + RBAC over HTTP, against the seeded demo tenant (see app/seed.py)."""
from conftest import DEMO_PASSWORD, auth_headers, login


def test_login_success_returns_token_and_user(client):
    r = client.post('/api/auth/login', json={'email': 'admin@replica-pilot.example', 'password': DEMO_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body['token_type'] == 'bearer'
    assert body['user']['email'] == 'admin@replica-pilot.example'
    assert body['user']['role'] == 'tenant_admin'
    assert body['access_token']


def test_login_wrong_password_is_401(client):
    r = client.post('/api/auth/login', json={'email': 'admin@replica-pilot.example', 'password': 'not-the-password'})
    assert r.status_code == 401


def test_login_unknown_email_is_401(client):
    r = client.post('/api/auth/login', json={'email': 'nobody@example.com', 'password': DEMO_PASSWORD})
    assert r.status_code == 401


def test_missing_token_is_401(client):
    r = client.get('/api/dashboard')
    assert r.status_code == 401


def test_invalid_token_is_401(client):
    r = client.get('/api/dashboard', headers={'Authorization': 'Bearer not-a-real-jwt'})
    assert r.status_code == 401


def test_me_returns_current_identity(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get('/api/auth/me', headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body['email'] == 'haydar@replica-pilot.example'
    assert body['role'] == 'seller'


def test_wrong_role_is_403(client):
    # seller may not access the manager-only overview
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get('/api/manager/overview', headers=headers)
    assert r.status_code == 403


def test_correct_role_is_200(client):
    headers = auth_headers(client, 'admin@replica-pilot.example')
    r = client.get('/api/manager/overview', headers=headers)
    assert r.status_code == 200


def test_tenant_admin_only_endpoint_rejects_manager(client):
    headers = auth_headers(client, 'manager@replica-pilot.example')
    r = client.get('/api/integrations', headers=headers)
    assert r.status_code == 403


def test_disabled_user_cannot_log_in_or_use_existing_token(client):
    admin_headers = auth_headers(client, 'admin@replica-pilot.example')
    created = client.post(
        '/api/admin/users', headers=admin_headers,
        json={'email': 'temp-seller@replica-pilot.example', 'password': 'a-strong-password-1', 'role': 'seller'},
    )
    assert created.status_code == 200
    user_id = created.json()['id']

    # token issued while still active must work
    token = login(client, 'temp-seller@replica-pilot.example', 'a-strong-password-1')
    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200

    deact = client.post(f'/api/admin/users/{user_id}/deactivate', headers=admin_headers)
    assert deact.status_code == 200
    assert deact.json()['is_active'] is False

    # a previously issued, still-unexpired token must stop working immediately
    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 403

    # and logging in again must also fail
    r = client.post('/api/auth/login', json={'email': 'temp-seller@replica-pilot.example', 'password': 'a-strong-password-1'})
    assert r.status_code == 403

    reactivated = client.post(f'/api/admin/users/{user_id}/activate', headers=admin_headers)
    assert reactivated.status_code == 200
    assert reactivated.json()['is_active'] is True
    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200


def test_tenant_admin_cannot_create_system_admin(client):
    admin_headers = auth_headers(client, 'admin@replica-pilot.example')
    r = client.post(
        '/api/admin/users', headers=admin_headers,
        json={'email': 'sneaky@replica-pilot.example', 'password': 'a-strong-password-1', 'role': 'system_admin'},
    )
    assert r.status_code == 422  # role not in the allowed literal set for this endpoint
