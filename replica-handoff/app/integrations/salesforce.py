from __future__ import annotations
import httpx
from ..config import get_settings


def status() -> dict:
    s = get_settings()
    return {'provider': 'salesforce', 'connected': bool(s.salesforce_instance_url and s.salesforce_access_token)}


async def query(soql: str) -> dict:
    s = get_settings()
    if not s.salesforce_instance_url or not s.salesforce_access_token:
        return {'connected': False, 'records': [], 'message': 'Salesforce-Zugangsdaten fehlen.'}
    url = s.salesforce_instance_url.rstrip('/') + '/services/data/v63.0/query'
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params={'q': soql}, headers={'Authorization': f'Bearer {s.salesforce_access_token}'})
        response.raise_for_status()
        return {'connected': True, **response.json()}


async def recent_opportunities(limit: int = 20) -> dict:
    return await query(
        f'SELECT Id, Name, StageName, Amount, CloseDate, IsWon, LastModifiedDate FROM Opportunity ORDER BY LastModifiedDate DESC LIMIT {min(limit, 100)}'
    )
