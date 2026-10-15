import asyncio
import logging
import httpx
from typing import Dict, List, Optional

logger = logging.getLogger("proxypulse.geoip")

# In-memory cache for resolved IP locations: IP -> {"code": "US", "name": "United States", "city": "New York"}
_GEO_CACHE: Dict[str, Dict[str, str]] = {}

# Queue for batch resolving unknown IPs
_PENDING_IPS = set()
_BATCH_LOCK = asyncio.Lock()

async def get_geo_info(ip: str) -> Dict[str, str]:
    """Retrieve geo info from cache or return placeholder while queuing batch lookup."""
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]
    
    # Private / localhost check
    if ip.startswith(("127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3")):
        res = {"code": "LAN", "name": "Local Network", "city": "Internal"}
        _GEO_CACHE[ip] = res
        return res

    _PENDING_IPS.add(ip)
    return {"code": "XX", "name": "Resolving...", "city": ""}

async def resolve_batch_ips(ips: List[str]) -> Dict[str, Dict[str, str]]:
    """Batch resolve up to 100 IPs using ip-api batch endpoint."""
    to_resolve = [ip for ip in ips if ip not in _GEO_CACHE][:100]
    if not to_resolve:
        return {ip: _GEO_CACHE.get(ip, {"code": "XX", "name": "Unknown", "city": ""}) for ip in ips}

    payload = [{"query": ip, "fields": "status,country,countryCode,city,query"} for ip in to_resolve]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post("http://ip-api.com/batch", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    query_ip = item.get("query")
                    if item.get("status") == "success":
                        geo = {
                            "code": item.get("countryCode", "XX"),
                            "name": item.get("country", "Unknown"),
                            "city": item.get("city", "")
                        }
                    else:
                        geo = {"code": "XX", "name": "Unknown", "city": ""}
                    _GEO_CACHE[query_ip] = geo
    except Exception as e:
        logger.debug("GeoIP batch lookup error: %s", e)
        for ip in to_resolve:
            if ip not in _GEO_CACHE:
                _GEO_CACHE[ip] = {"code": "XX", "name": "Unknown", "city": ""}

    return {ip: _GEO_CACHE.get(ip, {"code": "XX", "name": "Unknown", "city": ""}) for ip in ips}

async def background_geo_worker():
    """Background worker to continuously process queued IPs in batches of 100."""
    while True:
        try:
            if _PENDING_IPS:
                async with _BATCH_LOCK:
                    batch = list(_PENDING_IPS)[:100]
                    for ip in batch:
                        _PENDING_IPS.discard(ip)
                if batch:
                    await resolve_batch_ips(batch)
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Geo worker error: %s", e)
            await asyncio.sleep(5.0)
