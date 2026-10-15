import asyncio
import time
import logging
import json
import aiohttp
from aiohttp_socks import ProxyConnector
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime

from app.config import settings
from app.database import get_db_connection
from app.geoip import get_geo_info

logger = logging.getLogger("proxypulse.checker")

class CheckerManager:
    def __init__(self):
        self.is_running = False
        self.current_task: Optional[asyncio.Task] = None
        self.stats = {
            "total_to_check": 0,
            "checked": 0,
            "alive": 0,
            "dead": 0,
            "checks_per_second": 0.0,
            "start_time": 0.0,
        }

    async def check_proxy(self, ip: str, port: int, protocol: str, timeout: float = None) -> Dict[str, Any]:
        """
        Tests a single proxy for reachability, latency, and anonymity.
        Returns: {
            "alive": bool,
            "latency": int (ms),
            "anonymity": str ("elite", "anonymous", "transparent", "dead"),
            "ip": str,
            "port": int,
            "protocol": str,
            "country_code": str,
            "country_name": str,
            "city": str
        }
        """
        if timeout is None:
            timeout = settings.CHECKER_TIMEOUT

        proto_url = protocol.lower()
        if proto_url == "https":
            proxy_url = f"http://{ip}:{port}"
        else:
            proxy_url = f"{proto_url}://{ip}:{port}"

        target_url = settings.CHECK_TARGET_URL
        client_timeout = aiohttp.ClientTimeout(total=timeout, connect=timeout * 0.7)

        start_time = time.perf_counter()
        alive = False
        latency = None
        anonymity = "unknown"

        try:
            connector = ProxyConnector.from_url(proxy_url, ssl=False)
            async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
                async with session.get(target_url, headers={"User-Agent": "Mozilla/5.0 ProxyPulse/1.0"}) as resp:
                    if resp.status in (200, 204, 301, 302):
                        elapsed = (time.perf_counter() - start_time) * 1000
                        latency = max(1, int(elapsed))
                        alive = True

                        # Try to read response to evaluate anonymity
                        try:
                            text = await resp.text()
                            if "origin" in text:
                                data = json.loads(text)
                                origin = data.get("origin", "")
                                # If origin contains multiple IPs (comma separated), user IP is leaked
                                if "," in origin:
                                    anonymity = "transparent"
                                else:
                                    # Single IP observed
                                    anonymity = "elite"
                            else:
                                anonymity = "anonymous"
                        except Exception:
                            anonymity = "anonymous"
        except Exception as e:
            alive = False
            anonymity = "dead"
            latency = None

        # GeoIP Lookup
        geo = await get_geo_info(ip)

        return {
            "alive": alive,
            "latency": latency,
            "anonymity": anonymity if alive else "dead",
            "ip": ip,
            "port": port,
            "protocol": protocol,
            "country_code": geo.get("code", "XX"),
            "country_name": geo.get("name", "Unknown"),
            "city": geo.get("city", "")
        }

    async def start_checking(self, only_unchecked: bool = False, broadcast_fn: Optional[Callable] = None):
        if self.is_running:
            return False

        self.is_running = True
        self.stats = {
            "total_to_check": 0,
            "checked": 0,
            "alive": 0,
            "dead": 0,
            "checks_per_second": 0.0,
            "start_time": time.time(),
        }

        self.current_task = asyncio.create_task(self._run_checker(only_unchecked, broadcast_fn))
        return True

    async def stop_checking(self):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.is_running = False

    async def _run_checker(self, only_unchecked: bool, broadcast_fn: Optional[Callable]):
        conn = await get_db_connection()
        try:
            if only_unchecked:
                query = "SELECT id, ip, port, protocol FROM proxies WHERE last_checked_at IS NULL"
            else:
                query = "SELECT id, ip, port, protocol FROM proxies ORDER BY last_checked_at ASC NULLS FIRST"

            cursor = await conn.execute(query)
            proxies = [dict(row) for row in await cursor.fetchall()]
            self.stats["total_to_check"] = len(proxies)
            self.stats["start_time"] = time.time()

            if broadcast_fn:
                await broadcast_fn("checker_start", self.stats)

            if not proxies:
                return

            semaphore = asyncio.Semaphore(settings.CHECKER_CONCURRENCY)
            save_lock = asyncio.Lock()
            batch_updates = []

            async def check_item(p):
                if not self.is_running:
                    return

                async with semaphore:
                    result = await self.check_proxy(p["ip"], p["port"], p["protocol"])

                    async with save_lock:
                        batch_updates.append((
                            1 if result["alive"] else 0,
                            result["latency"],
                            result["anonymity"],
                            result["country_code"],
                            result["country_name"],
                            result["city"],
                            datetime.utcnow().isoformat(),
                            1 if result["alive"] else 0,
                            0 if result["alive"] else 1,
                            p["id"]
                        ))

                        self.stats["checked"] += 1
                        if result["alive"]:
                            self.stats["alive"] += 1
                        else:
                            self.stats["dead"] += 1

                        elapsed = max(0.1, time.time() - self.stats["start_time"])
                        self.stats["checks_per_second"] = round(self.stats["checked"] / elapsed, 1)

                        # Flush to DB every 50 checked or when done
                        if len(batch_updates) >= 50:
                            await self._flush_batch(conn, batch_updates)
                            batch_updates.clear()

                    if broadcast_fn and (self.stats["checked"] % 5 == 0 or self.stats["checked"] == self.stats["total_to_check"]):
                        await broadcast_fn("checker_progress", {
                            **self.stats,
                            "last_result": result
                        })

            tasks = [check_item(p) for p in proxies]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Flush remaining
            if batch_updates:
                await self._flush_batch(conn, batch_updates)
                batch_updates.clear()

        except asyncio.CancelledError:
            logger.info("Checker cancelled by user.")
        except Exception as e:
            logger.error("Error during checking: %s", e)
        finally:
            self.is_running = False
            await conn.close()
            if broadcast_fn:
                await broadcast_fn("checker_done", self.stats)

    async def _flush_batch(self, conn, batch_updates):
        try:
            await conn.executemany("""
                UPDATE proxies SET
                    alive = ?,
                    latency = ?,
                    anonymity = ?,
                    country_code = ?,
                    country_name = ?,
                    city = ?,
                    last_checked_at = ?,
                    success_count = success_count + ?,
                    fail_count = fail_count + ?
                WHERE id = ?
            """, batch_updates)
            await conn.commit()
        except Exception as e:
            logger.error("Failed to flush batch update to database: %s", e)

checker_manager = CheckerManager()
