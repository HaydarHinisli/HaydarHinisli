"""Password hashing and JWT session tokens.

Pilot-grade, not final production hardening: password hashing uses stdlib
hashlib.pbkdf2_hmac (no extra native dependency) rather than bcrypt/argon2, and
tokens are self-contained JWTs rather than server-side revocable sessions. Both are
documented, tracked gaps (see README "Produktionslücken" and docs/DECISIONS.md
ADR-018), not an oversight — full OAuth + a revocable session store is Sprint 2+ work.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
import time

import jwt

from ..config import get_settings

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return f'pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


def create_access_token(*, user_id: int, company_id: int | None, role: str) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        'sub': str(user_id),
        'company_id': company_id,
        'role': role,
        'iat': now,
        'exp': now + settings.replica_jwt_expires_minutes * 60,
    }
    return jwt.encode(payload, settings.replica_jwt_secret, algorithm='HS256')


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.replica_jwt_secret, algorithms=['HS256'])
