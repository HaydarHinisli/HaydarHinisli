"""Production integration seam for OpenAI Realtime.

The MVP does not open a paid realtime session automatically. A production coder can
bridge Twilio/WebRTC audio here and keep the API key server-side.
"""
from __future__ import annotations
from ..config import get_settings


def status() -> dict:
    s = get_settings()
    return {
        'provider': 'openai_realtime',
        'connected': bool(s.openai_api_key),
        'model': s.openai_realtime_model,
        'mode': 'server_side_websocket',
    }


def session_blueprint() -> dict:
    s = get_settings()
    return {
        'url': f'wss://api.openai.com/v1/realtime?model={s.openai_realtime_model}',
        'required_headers': ['Authorization: Bearer <server-side key>', 'OpenAI-Safety-Identifier: <stable hashed actor id>'],
        'note': 'Never expose the project API key in the browser.',
    }
