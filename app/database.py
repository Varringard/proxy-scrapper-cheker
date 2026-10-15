import aiosqlite
import logging
from app.config import settings

logger = logging.getLogger("proxypulse.db")

async def get_db_connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(settings.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA busy_timeout = 5000")
    return conn

async def init_db():
    conn = await get_db_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                protocol TEXT NOT NULL,
                alive INTEGER DEFAULT 0,
                latency INTEGER DEFAULT NULL,
                anonymity TEXT DEFAULT 'unknown',
                country_code TEXT DEFAULT '',
                country_name TEXT DEFAULT '',
                city TEXT DEFAULT '',
                source TEXT DEFAULT '',
                last_checked_at TIMESTAMP,
                fail_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ip, port, protocol)
            )
        """)
        
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_proxies_alive ON proxies(alive)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_proxies_protocol ON proxies(protocol)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_proxies_country ON proxies(country_code)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_proxies_latency ON proxies(latency)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                protocol TEXT DEFAULT 'all',
                enabled INTEGER DEFAULT 1,
                last_scraped_at TIMESTAMP,
                proxies_found INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        await conn.commit()
    finally:
        await conn.close()
    logger.info("Database schema initialized at %s", settings.DB_PATH)
