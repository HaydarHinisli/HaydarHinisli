"""Structured, per-request operational logging — deliberately separate from the
AuditEvent table (docs item 11: "Audit Logging von normalem Application Logging
getrennt halten"). This module writes one JSON line per HTTP request to stdout via
Python's stdlib `logging`; AuditEvent rows are compliance/business records written by
app/compliance/audit.py into the database. Different storage, different code path,
different retention/immutability expectations — never conflate the two.

Fields logged: request_id, method, path, status_code, latency_ms, tenant_id, user_id,
error_class. Deliberately NOT logged: request/response bodies, prospect_text,
suggestion content, consent evidence, tokens/passwords — anything that could contain
real prospect or credential data (see docs/SECURITY_PRIVACY.md §5 data minimization).
"""
from __future__ import annotations
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

ACCESS_LOGGER_NAME = 'replica.access'


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        extra = getattr(record, 'fields', None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    if logger.handlers:
        return  # idempotent: don't double-attach handlers on reload/re-import
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@dataclass
class _RequestState:
    request_id: str
    fields: dict = field(default_factory=dict)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request_id, times the request, and logs one structured access-log
    line per request. tenant_id/user_id are read from request.state, which the auth
    dependency (app/auth/dependencies.get_current_user) populates during the call —
    request.state is shared for the whole Request lifecycle, so it's already set by
    the time this middleware reads it after `call_next` returns.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        error_class = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:  # re-raised after logging so FastAPI's own handlers still run
            error_class = type(exc).__name__
            status_code = 500
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self._log(request, request_id, status_code, latency_ms, error_class)
            raise
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self._log(request, request_id, status_code, latency_ms, error_class)
        response.headers['X-Request-ID'] = request_id
        return response

    @staticmethod
    def _log(request: Request, request_id: str, status_code: int, latency_ms: float, error_class: str | None) -> None:
        logger = logging.getLogger(ACCESS_LOGGER_NAME)
        logger.info(
            'request',
            extra={'fields': {
                'request_id': request_id,
                'method': request.method,
                'path': request.url.path,
                'status_code': status_code,
                'latency_ms': latency_ms,
                'tenant_id': getattr(request.state, 'company_id', None),
                'user_id': getattr(request.state, 'user_id', None),
                'error_class': error_class,
            }},
        )
