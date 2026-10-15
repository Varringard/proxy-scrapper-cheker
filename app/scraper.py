import asyncio
import re
import logging
import httpx
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Callable
from app.database import get_db_connection

logger = logging.getLogger("proxypulse.scraper")

IP_PORT_REGEX = re.compile(
    r'(?:(https?|socks4|socks5)://)?'
    r'(\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b)'
    r':(\d{2,5})'
)

DEFAULT_SOURCES = [
    # TheSpeedX
    {"name": "TheSpeedX HTTP", "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt", "protocol": "http"},
    {"name": "TheSpeedX SOCKS4", "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt", "protocol": "socks4"},
    {"name": "TheSpeedX SOCKS5", "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt", "protocol": "socks5"},
    
    # Monosans
    {"name": "Monosans HTTP", "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "protocol": "http"},
    {"name": "Monosans SOCKS4", "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt", "protocol": "socks4"},
    {"name": "Monosans SOCKS5", "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "protocol": "socks5"},
    
    # ShiftyTR
    {"name": "ShiftyTR HTTP", "url": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "protocol": "http"},
    {"name": "ShiftyTR HTTPS", "url": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt", "protocol": "https"},
    {"name": "ShiftyTR SOCKS4", "url": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt", "protocol": "socks4"},
    {"name": "ShiftyTR SOCKS5", "url": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", "protocol": "socks5"},
    
    # Jetkai
    {"name": "Jetkai HTTP", "url": "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt", "protocol": "http"},
    {"name": "Jetkai HTTPS", "url": "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt", "protocol": "https"},
    {"name": "Jetkai SOCKS4", "url": "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt", "protocol": "socks4"},
    {"name": "Jetkai SOCKS5", "url": "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt", "protocol": "socks5"},

    # Roosterkid
    {"name": "Roosterkid HTTPS", "url": "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt", "protocol": "https"},
    {"name": "Roosterkid SOCKS4", "url": "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt", "protocol": "socks4"},
    {"name": "Roosterkid SOCKS5", "url": "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt", "protocol": "socks5"},

    # Hookzof
    {"name": "Hookzof SOCKS5", "url": "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "protocol": "socks5"},

    # ProxyScrape Free API
    {"name": "ProxyScrape HTTP", "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http&proxy_format=ipport&format=text", "protocol": "http"},
    {"name": "ProxyScrape SOCKS4", "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=socks4&proxy_format=ipport&format=text", "protocol": "socks4"},
    {"name": "ProxyScrape SOCKS5", "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=socks5&proxy_format=ipport&format=text", "protocol": "socks5"},

    # Sunny9577
    {"name": "Sunny9577 HTTP", "url": "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/http_proxies.txt", "protocol": "http"},
    {"name": "Sunny9577 SOCKS4", "url": "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks4_proxies.txt", "protocol": "socks4"},
    {"name": "Sunny9577 SOCKS5", "url": "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks5_proxies.txt", "protocol": "socks5"},

    # MuRongPIG
    {"name": "MuRongPIG HTTP", "url": "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt", "protocol": "http"},
    {"name": "MuRongPIG SOCKS4", "url": "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks4.txt", "protocol": "socks4"},
    {"name": "MuRongPIG SOCKS5", "url": "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks5.txt", "protocol": "socks5"},

    # Zloi-user
    {"name": "Zloi-user HTTP", "url": "https://raw.githubusercontent.com/zloi-user/hideip.me/master/http.txt", "protocol": "http"},
    {"name": "Zloi-user HTTPS", "url": "https://raw.githubusercontent.com/zloi-user/hideip.me/master/https.txt", "protocol": "https"},
    {"name": "Zloi-user SOCKS4", "url": "https://raw.githubusercontent.com/zloi-user/hideip.me/master/socks4.txt", "protocol": "socks4"},
    {"name": "Zloi-user SOCKS5", "url": "https://raw.githubusercontent.com/zloi-user/hideip.me/master/socks5.txt", "protocol": "socks5"},

    # Prxchk
    {"name": "Prxchk HTTP", "url": "https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt", "protocol": "http"},
    {"name": "Prxchk SOCKS4", "url": "https://raw.githubusercontent.com/prxchk/proxy-list/main/socks4.txt", "protocol": "socks4"},
    {"name": "Prxchk SOCKS5", "url": "https://raw.githubusercontent.com/prxchk/proxy-list/main/socks5.txt", "protocol": "socks5"},

    # Vakhov
    {"name": "Vakhov HTTP", "url": "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt", "protocol": "http"},
    {"name": "Vakhov SOCKS4", "url": "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt", "protocol": "socks4"},
    {"name": "Vakhov SOCKS5", "url": "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt", "protocol": "socks5"},
]

class ScraperManager:
    def __init__(self):
        self.is_running = False
        self.current_task: Optional[asyncio.Task] = None
        self.stats = {
            "total_found": 0,
            "new_added": 0,
            "sources_scraped": 0,
            "sources_total": 0,
            "current_source": "",
        }

    async def init_sources(self):
        """Seed default sources into database if not already present."""
        conn = await get_db_connection()
        try:
            for s in DEFAULT_SOURCES:
                await conn.execute("""
                    INSERT OR IGNORE INTO sources (name, url, protocol, enabled)
                    VALUES (?, ?, ?, 1)
                """, (s["name"], s["url"], s["protocol"]))
            await conn.commit()
        finally:
            await conn.close()

    def parse_proxies_from_text(self, text: str, default_protocol: str = "http") -> List[Tuple[str, int, str]]:
        """Extract valid (ip, port, protocol) from any raw text format."""
        results = []
        for match in IP_PORT_REGEX.finditer(text):
            proto_prefix, ip, port_str = match.groups()
            port = int(port_str)
            if not (1 <= port <= 65535):
                continue
            
            # Determine protocol
            protocol = proto_prefix.lower() if proto_prefix else default_protocol.lower()
            if protocol not in ("http", "https", "socks4", "socks5"):
                protocol = default_protocol.lower()
            
            results.append((ip, port, protocol))
        return results

    async def scrape_source(self, client: httpx.AsyncClient, source: dict) -> List[Tuple[str, int, str]]:
        url = source["url"]
        default_proto = source["protocol"] if source["protocol"] != "all" else "http"
        try:
            resp = await client.get(url, timeout=12.0)
            if resp.status_code == 200:
                return self.parse_proxies_from_text(resp.text, default_proto)
        except Exception as e:
            logger.debug("Failed to scrape %s (%s): %s", source.get("name"), url, e)
        return []

    async def start_scraping(self, broadcast_fn: Optional[Callable] = None):
        if self.is_running:
            return False

        self.is_running = True
        self.stats = {
            "total_found": 0,
            "new_added": 0,
            "sources_scraped": 0,
            "sources_total": 0,
            "current_source": "",
        }

        self.current_task = asyncio.create_task(self._run_scraper(broadcast_fn))
        return True

    async def stop_scraping(self):
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.is_running = False

    async def _run_scraper(self, broadcast_fn: Optional[Callable]):
        conn = await get_db_connection()
        try:
            cursor = await conn.execute("SELECT id, name, url, protocol FROM sources WHERE enabled = 1")
            sources = [dict(row) for row in await cursor.fetchall()]
            self.stats["sources_total"] = len(sources)

            if broadcast_fn:
                await broadcast_fn("scraper_start", self.stats)

            # High concurrency async scraping of sources
            async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, follow_redirects=True) as client:
                semaphore = asyncio.Semaphore(10)

                async def scrape_and_save(src):
                    if not self.is_running:
                        return
                    async with semaphore:
                        self.stats["current_source"] = src["name"]
                        if broadcast_fn:
                            await broadcast_fn("scraper_progress", self.stats)

                        proxies = await self.scrape_source(client, src)
                        found_count = len(proxies)
                        new_count = 0

                        if proxies:
                            # Batch insert
                            rows = [(p[0], p[1], p[2], src["name"]) for p in proxies]
                            # Use transaction
                            async with conn.cursor() as cur:
                                before_count = (await (await conn.execute("SELECT COUNT(*) FROM proxies")).fetchone())[0]
                                await cur.executemany("""
                                    INSERT OR IGNORE INTO proxies (ip, port, protocol, source)
                                    VALUES (?, ?, ?, ?)
                                """, rows)
                                await conn.commit()
                                after_count = (await (await conn.execute("SELECT COUNT(*) FROM proxies")).fetchone())[0]
                                new_count = after_count - before_count

                        # Update source stats
                        now_str = datetime.utcnow().isoformat()
                        await conn.execute("""
                            UPDATE sources SET last_scraped_at = ?, proxies_found = ? WHERE id = ?
                        """, (now_str, found_count, src["id"]))
                        await conn.commit()

                        self.stats["total_found"] += found_count
                        self.stats["new_added"] += new_count
                        self.stats["sources_scraped"] += 1

                        if broadcast_fn:
                            await broadcast_fn("scraper_progress", self.stats)

                tasks = [scrape_and_save(s) for s in sources]
                await asyncio.gather(*tasks, return_exceptions=True)

            logger.info("Scraping finished. Found: %d, New: %d", self.stats["total_found"], self.stats["new_added"])
        except asyncio.CancelledError:
            logger.info("Scraping cancelled by user.")
        except Exception as e:
            logger.error("Error during scraping: %s", e)
        finally:
            self.is_running = False
            await conn.close()
            if broadcast_fn:
                await broadcast_fn("scraper_done", self.stats)

scraper_manager = ScraperManager()
