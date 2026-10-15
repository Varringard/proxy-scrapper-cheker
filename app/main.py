import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, PlainTextResponse, JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.database import init_db, get_db_connection
from app.geoip import background_geo_worker
from app.scraper import scraper_manager
from app.checker import checker_manager
from app.gateway import gateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("proxypulse")

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: Any):
        if not self.active_connections:
            return
        payload = {"event": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()}
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(payload)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

ws_manager = ConnectionManager()

# Background automation loops
async def periodic_scraper_loop():
    if settings.AUTO_SCRAPE_INTERVAL <= 0:
        return
    while True:
        await asyncio.sleep(settings.AUTO_SCRAPE_INTERVAL)
        if not scraper_manager.is_running:
            logger.info("Triggering scheduled proxy scrape...")
            await scraper_manager.start_scraping(ws_manager.broadcast)

async def periodic_checker_loop():
    if settings.AUTO_CHECK_INTERVAL <= 0:
        return
    while True:
        await asyncio.sleep(settings.AUTO_CHECK_INTERVAL)
        if not checker_manager.is_running:
            logger.info("Triggering scheduled proxy check...")
            await checker_manager.start_checking(only_unchecked=False, broadcast_fn=ws_manager.broadcast)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s...", settings.APP_NAME, settings.VERSION)
    await init_db()
    await scraper_manager.init_sources()
    
    # Launch background tasks
    geo_task = asyncio.create_task(background_geo_worker())
    scrape_loop_task = asyncio.create_task(periodic_scraper_loop())
    check_loop_task = asyncio.create_task(periodic_checker_loop())
    
    # Start rotating gateway
    if settings.GATEWAY_ENABLED:
        await gateway.start()

    yield

    # Shutdown
    logger.info("Shutting down %s...", settings.APP_NAME)
    geo_task.cancel()
    scrape_loop_task.cancel()
    check_loop_task.cancel()
    await scraper_manager.stop_scraping()
    await checker_manager.stop_checking()
    if settings.GATEWAY_ENABLED:
        await gateway.stop()

app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── WEBSOCKET ───────────────────────────────────────────────────────────────

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial status
        await websocket.send_json({
            "event": "connected",
            "data": {
                "scraper_running": scraper_manager.is_running,
                "checker_running": checker_manager.is_running,
                "gateway_running": gateway.is_running,
                "gateway_port": settings.GATEWAY_PORT
            }
        })
        while True:
            # Keep connection alive / receive client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# ─── STATS & DASHBOARD ───────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    conn = await get_db_connection()
    try:
        total = (await (await conn.execute("SELECT COUNT(*) FROM proxies")).fetchone())[0]
        alive = (await (await conn.execute("SELECT COUNT(*) FROM proxies WHERE alive = 1")).fetchone())[0]
        dead = (await (await conn.execute("SELECT COUNT(*) FROM proxies WHERE alive = 0 AND last_checked_at IS NOT NULL")).fetchone())[0]
        unchecked = (await (await conn.execute("SELECT COUNT(*) FROM proxies WHERE last_checked_at IS NULL")).fetchone())[0]
        
        # Average Latency
        avg_row = await (await conn.execute("SELECT AVG(latency) FROM proxies WHERE alive = 1 AND latency IS NOT NULL")).fetchone()
        avg_latency = round(avg_row[0], 0) if avg_row and avg_row[0] is not None else 0

        # Protocols Breakdown
        proto_cursor = await conn.execute("""
            SELECT protocol, COUNT(*) as count, SUM(CASE WHEN alive = 1 THEN 1 ELSE 0 END) as alive_count
            FROM proxies GROUP BY protocol
        """)
        protocols = [dict(r) for r in await proto_cursor.fetchall()]

        # Anonymity Breakdown
        anon_cursor = await conn.execute("""
            SELECT anonymity, COUNT(*) as count
            FROM proxies WHERE alive = 1 GROUP BY anonymity
        """)
        anonymity = [dict(r) for r in await anon_cursor.fetchall()]

        # Top Countries
        country_cursor = await conn.execute("""
            SELECT country_code, country_name, COUNT(*) as count
            FROM proxies WHERE alive = 1 AND country_code != '' AND country_code != 'XX'
            GROUP BY country_code ORDER BY count DESC LIMIT 10
        """)
        countries = [dict(r) for r in await country_cursor.fetchall()]

        return {
            "total": total,
            "alive": alive,
            "dead": dead,
            "unchecked": unchecked,
            "avg_latency": avg_latency,
            "protocols": protocols,
            "anonymity": anonymity,
            "top_countries": countries,
            "scraper_running": scraper_manager.is_running,
            "checker_running": checker_manager.is_running,
            "gateway": {
                "enabled": gateway.is_running,
                "port": settings.GATEWAY_PORT,
                "strategy": settings.GATEWAY_STRATEGY,
                "active_connections": gateway.active_connections,
                "total_requests": gateway.total_requests
            }
        }
    finally:
        await conn.close()

# ─── PROXIES LIST & FILTERING ────────────────────────────────────────────────

@app.get("/api/proxies")
async def list_proxies(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    protocol: Optional[str] = None,
    alive: Optional[int] = None,
    country: Optional[str] = None,
    anonymity: Optional[str] = None,
    search: Optional[str] = None,
    max_latency: Optional[int] = None,
    sort_by: str = Query("id", regex="^(id|latency|last_checked_at|ip|country_code)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$")
):
    conn = await get_db_connection()
    try:
        clauses = []
        params = []

        if protocol:
            clauses.append("protocol = ?")
            params.append(protocol.lower())
        if alive is not None:
            clauses.append("alive = ?")
            params.append(alive)
        if country:
            clauses.append("country_code = ?")
            params.append(country.upper())
        if anonymity:
            clauses.append("anonymity = ?")
            params.append(anonymity.lower())
        if max_latency:
            clauses.append("latency <= ?")
            params.append(max_latency)
        if search:
            clauses.append("(ip LIKE ? OR CAST(port AS TEXT) LIKE ? OR country_name LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Total count query
        count_cursor = await conn.execute(f"SELECT COUNT(*) FROM proxies {where_sql}", params)
        total = (await count_cursor.fetchone())[0]

        # Order by handling
        nulls_clause = "NULLS LAST" if sort_order.lower() == "asc" else "NULLS FIRST"
        order_sql = f"ORDER BY {sort_by} {sort_order.upper()} {nulls_clause}"

        # Fetch records
        offset = (page - 1) * limit
        data_sql = f"SELECT * FROM proxies {where_sql} {order_sql} LIMIT ? OFFSET ?"
        data_cursor = await conn.execute(data_sql, params + [limit, offset])
        rows = [dict(r) for r in await data_cursor.fetchall()]

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "items": rows
        }
    finally:
        await conn.close()

# ─── ACTIONS (SCRAPER & CHECKER) ─────────────────────────────────────────────

@app.post("/api/scraper/start")
async def start_scraper():
    success = await scraper_manager.start_scraping(ws_manager.broadcast)
    if not success:
        return {"status": "error", "message": "Scraper is already running"}
    return {"status": "success", "message": "Scraper started"}

@app.post("/api/scraper/stop")
async def stop_scraper():
    await scraper_manager.stop_scraping()
    await ws_manager.broadcast("scraper_stopped", {})
    return {"status": "success", "message": "Scraper stopped"}

@app.post("/api/checker/start")
async def start_checker(only_unchecked: bool = Query(False)):
    success = await checker_manager.start_checking(only_unchecked, ws_manager.broadcast)
    if not success:
        return {"status": "error", "message": "Checker is already running"}
    return {"status": "success", "message": "Checker started"}

@app.post("/api/checker/stop")
async def stop_checker():
    await checker_manager.stop_checking()
    await ws_manager.broadcast("checker_stopped", {})
    return {"status": "success", "message": "Checker stopped"}

@app.post("/api/proxies/check-one/{proxy_id}")
async def check_single_proxy(proxy_id: int):
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT id, ip, port, protocol FROM proxies WHERE id = ?", (proxy_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Proxy not found")

        result = await checker_manager.check_proxy(row["ip"], row["port"], row["protocol"])
        
        # Save to DB
        await conn.execute("""
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
        """, (
            1 if result["alive"] else 0,
            result["latency"],
            result["anonymity"],
            result["country_code"],
            result["country_name"],
            result["city"],
            datetime.utcnow().isoformat(),
            1 if result["alive"] else 0,
            0 if result["alive"] else 1,
            proxy_id
        ))
        await conn.commit()
        return result
    finally:
        await conn.close()

# ─── IMPORT & DELETE ─────────────────────────────────────────────────────────

class ImportRequest(BaseModel):
    text: str
    default_protocol: str = "http"

@app.post("/api/proxies/import")
async def import_proxies(req: ImportRequest):
    proxies = scraper_manager.parse_proxies_from_text(req.text, req.default_protocol)
    if not proxies:
        return {"status": "warning", "message": "No valid proxies found in text", "added": 0}

    conn = await get_db_connection()
    try:
        before = (await (await conn.execute("SELECT COUNT(*) FROM proxies")).fetchone())[0]
        rows = [(p[0], p[1], p[2], "Manual Import") for p in proxies]
        await conn.executemany("""
            INSERT OR IGNORE INTO proxies (ip, port, protocol, source)
            VALUES (?, ?, ?, ?)
        """, rows)
        await conn.commit()
        after = (await (await conn.execute("SELECT COUNT(*) FROM proxies")).fetchone())[0]
        added = after - before
        return {"status": "success", "found": len(proxies), "added": added}
    finally:
        await conn.close()

@app.delete("/api/proxies/dead")
async def delete_dead_proxies():
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("DELETE FROM proxies WHERE alive = 0 AND last_checked_at IS NOT NULL")
        deleted = cursor.rowcount
        await conn.commit()
        return {"status": "success", "deleted": deleted}
    finally:
        await conn.close()

@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int):
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        await conn.commit()
        return {"status": "success", "deleted": cursor.rowcount}
    finally:
        await conn.close()

# ─── EXPORT API ──────────────────────────────────────────────────────────────

@app.get("/api/export")
async def export_proxies(
    format: str = Query("txt", regex="^(txt|json|csv|pac|proxychains)$"),
    protocol: Optional[str] = None,
    alive: Optional[int] = 1,
    country: Optional[str] = None,
    anonymity: Optional[str] = None,
    max_latency: Optional[int] = None,
    with_protocol: bool = Query(False)
):
    conn = await get_db_connection()
    try:
        clauses = []
        params = []
        if alive is not None:
            clauses.append("alive = ?")
            params.append(alive)
        if protocol:
            clauses.append("protocol = ?")
            params.append(protocol.lower())
        if country:
            clauses.append("country_code = ?")
            params.append(country.upper())
        if anonymity:
            clauses.append("anonymity = ?")
            params.append(anonymity.lower())
        if max_latency:
            clauses.append("latency <= ?")
            params.append(max_latency)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT ip, port, protocol, latency, anonymity, country_code FROM proxies {where_sql} ORDER BY latency ASC NULLS LAST"
        cursor = await conn.execute(sql, params)
        rows = [dict(r) for r in await cursor.fetchall()]

        if format == "json":
            return JSONResponse(content=rows, headers={"Content-Disposition": "attachment; filename=proxies.json"})

        elif format == "csv":
            lines = ["ip,port,protocol,latency,anonymity,country"]
            for r in rows:
                lines.append(f"{r['ip']},{r['port']},{r['protocol']},{r['latency'] or ''},{r['anonymity']},{r['country_code']}")
            return Response(content="\n".join(lines), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=proxies.csv"})

        elif format == "proxychains":
            lines = ["# proxychains.conf format"]
            for r in rows:
                lines.append(f"{r['protocol']} {r['ip']} {r['port']}")
            return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": "attachment; filename=proxychains.txt"})

        elif format == "pac":
            proxy_list_str = "; ".join([f"PROXY {r['ip']}:{r['port']}" for r in rows[:50]])
            pac_content = f"""function FindProxyForURL(url, host) {{
    return "{proxy_list_str}; DIRECT";
}}"""
            return Response(content=pac_content, media_type="application/x-ns-proxy-autoconfig", headers={"Content-Disposition": "attachment; filename=proxy.pac"})

        else: # txt
            if with_protocol:
                lines = [f"{r['protocol']}://{r['ip']}:{r['port']}" for r in rows]
            else:
                lines = [f"{r['ip']}:{r['port']}" for r in rows]
            return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": "attachment; filename=proxies.txt"})
    finally:
        await conn.close()

# ─── SOURCES MANAGEMENT ──────────────────────────────────────────────────────

@app.get("/api/sources")
async def list_sources():
    conn = await get_db_connection()
    try:
        cursor = await conn.execute("SELECT * FROM sources ORDER BY id ASC")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await conn.close()

class SourceCreate(BaseModel):
    name: str
    url: str
    protocol: str = "all"

@app.post("/api/sources")
async def create_source(src: SourceCreate):
    conn = await get_db_connection()
    try:
        await conn.execute("""
            INSERT INTO sources (name, url, protocol, enabled) VALUES (?, ?, ?, 1)
        """, (src.name, src.url, src.protocol.lower()))
        await conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await conn.close()

@app.patch("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: int):
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE sources SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (source_id,))
        await conn.commit()
        return {"status": "success"}
    finally:
        await conn.close()

@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: int):
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await conn.commit()
        return {"status": "success"}
    finally:
        await conn.close()

# ─── GATEWAY MANAGEMENT & TEST ───────────────────────────────────────────────

class GatewayConfig(BaseModel):
    strategy: Optional[str] = None
    country: Optional[str] = None

@app.post("/api/gateway/config")
async def configure_gateway(cfg: GatewayConfig):
    if cfg.strategy and cfg.strategy in ("fastest", "random", "round-robin"):
        settings.GATEWAY_STRATEGY = cfg.strategy
    if cfg.country is not None:
        settings.GATEWAY_COUNTRY = cfg.country.upper()
    return {
        "status": "success",
        "strategy": settings.GATEWAY_STRATEGY,
        "country": settings.GATEWAY_COUNTRY
    }

@app.get("/api/gateway/test")
async def test_gateway():
    """Tests the rotating gateway locally and returns connection info."""
    import httpx
    if not gateway.is_running:
        raise HTTPException(status_code=400, detail="Gateway is not running")

    proxy_url = f"http://127.0.0.1:{settings.GATEWAY_PORT}"
    start = datetime.utcnow()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=8.0) as client:
            resp = await client.get("http://httpbin.org/ip")
            duration = int((datetime.utcnow() - start).total_seconds() * 1000)
            if resp.status_code == 200:
                ip_data = resp.json()
                return {
                    "status": "success",
                    "outgoing_ip": ip_data.get("origin"),
                    "latency_ms": duration,
                    "target": "httpbin.org"
                }
            else:
                return {"status": "error", "message": f"Gateway returned HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Connection test failed: {str(e)}"}

# Mount frontend static files
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
