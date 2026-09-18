from __future__ import annotations
from datetime import datetime, timezone
import httpx
from ..config import get_settings

BASE = 'https://www.googleapis.com/calendar/v3'


def status() -> dict:
    return {'provider': 'google_calendar', 'connected': bool(get_settings().google_calendar_access_token)}


async def upcoming_events(max_results: int = 20) -> dict:
    settings = get_settings()
    token = settings.google_calendar_access_token
    if not token:
        return {'connected': False, 'items': [], 'message': 'GOOGLE_CALENDAR_ACCESS_TOKEN fehlt.'}
    url = f'{BASE}/calendars/{settings.google_calendar_id}/events'
    params = {
        'timeMin': datetime.now(timezone.utc).isoformat(),
        'singleEvents': 'true',
        'orderBy': 'startTime',
        'maxResults': min(max_results, 100),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params=params, headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        payload = response.json()
    return {'connected': True, 'items': payload.get('items', [])}
