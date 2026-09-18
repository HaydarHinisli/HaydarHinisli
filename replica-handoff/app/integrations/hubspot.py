from __future__ import annotations
import httpx
from ..config import get_settings

BASE = 'https://api.hubapi.com'


def status() -> dict:
    token = get_settings().hubspot_access_token
    return {'provider': 'hubspot', 'connected': bool(token)}


async def _get(path: str, params: dict | None = None) -> dict:
    token = get_settings().hubspot_access_token
    if not token:
        return {'connected': False, 'results': [], 'message': 'HUBSPOT_ACCESS_TOKEN fehlt.'}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            BASE + path,
            params=params,
            headers={'Authorization': f'Bearer {token}'},
        )
        response.raise_for_status()
        return {'connected': True, **response.json()}


async def recent_meetings(limit: int = 20) -> dict:
    return await _get('/crm/v3/objects/meetings', {
        'limit': min(limit, 100),
        'properties': 'hs_meeting_title,hs_meeting_start_time,hs_meeting_end_time,hs_meeting_outcome',
        'archived': 'false',
    })


async def recent_deals(limit: int = 20) -> dict:
    return await _get('/crm/v3/objects/deals', {
        'limit': min(limit, 100),
        'properties': 'dealname,dealstage,amount,closedate,hs_is_closed_won',
        'archived': 'false',
    })
