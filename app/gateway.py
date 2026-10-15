import asyncio
import logging
import random
from typing import Optional, Dict, Any, List
from aiohttp_socks import ProxyType, ChainProxyConnector
import aiohttp
from app.config import settings
from app.database import get_db_connection

logger = logging.getLogger("proxypulse.gateway")

class RotatingGateway:
    def __init__(self):
        self.server: Optional[asyncio.Server] = None
        self.is_running = False
        self.round_robin_index = 0
        self.active_connections = 0
        self.total_requests = 0

    async def get_next_proxy(self) -> Optional[Dict[str, Any]]:
        conn = await get_db_connection()
        try:
            query = "SELECT ip, port, protocol, latency, country_code FROM proxies WHERE alive = 1"
            params = []
            if settings.GATEWAY_COUNTRY:
                query += " AND country_code = ?"
                params.append(settings.GATEWAY_COUNTRY.upper())

            if settings.GATEWAY_STRATEGY == "fastest":
                query += " ORDER BY latency ASC LIMIT 20"
            elif settings.GATEWAY_STRATEGY == "random":
                query += " ORDER BY RANDOM() LIMIT 20"
            else:  # round-robin
                query += " ORDER BY id ASC"

            cursor = await conn.execute(query, params)
            rows = [dict(r) for r in await cursor.fetchall()]
            if not rows:
                return None

            if settings.GATEWAY_STRATEGY == "round-robin":
                idx = self.round_robin_index % len(rows)
                self.round_robin_index += 1
                return rows[idx]
            elif settings.GATEWAY_STRATEGY == "fastest":
                return rows[0]
            else:
                return random.choice(rows)
        finally:
            await conn.close()

    async def handle_client(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
        self.active_connections += 1
        self.total_requests += 1
        try:
            # Read the HTTP request line
            request_line = await client_reader.readline()
            if not request_line:
                return

            line_str = request_line.decode("latin1", errors="ignore")
            parts = line_str.strip().split()
            if len(parts) < 2:
                return

            method, target = parts[0].upper(), parts[1]

            # Read remaining headers
            headers = []
            while True:
                header_line = await client_reader.readline()
                if not header_line or header_line == b"\r\n":
                    break
                headers.append(header_line)

            # Pick an upstream proxy
            upstream = await self.get_next_proxy()
            if not upstream:
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n\r\nNo alive proxies in pool.\r\n")
                await client_writer.drain()
                return

            u_ip = upstream["ip"]
            u_port = upstream["port"]
            u_proto = upstream["protocol"].lower()

            if method == "CONNECT":
                # HTTPS Tunneling (CONNECT host:port)
                if ":" in target:
                    host, port = target.split(":", 1)
                    port = int(port)
                else:
                    host, port = target, 443

                try:
                    if u_proto in ("socks4", "socks5"):
                        import socksio
                        # Direct TCP handshake with SOCKS or HTTP forwarder
                        remote_reader, remote_writer = await self._connect_socks(u_ip, u_port, u_proto, host, port)
                    else:
                        # Upstream HTTP proxy
                        remote_reader, remote_writer = await asyncio.open_connection(u_ip, u_port)
                        connect_cmd = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode()
                        remote_writer.write(connect_cmd)
                        await remote_writer.drain()

                        resp_line = await remote_reader.readline()
                        if b"200" not in resp_line:
                            client_writer.write(b"HTTP/1.1 502 Upstream Tunnel Failed\r\n\r\n")
                            await client_writer.drain()
                            remote_writer.close()
                            return
                        # Consume headers from proxy response
                        while True:
                            h = await remote_reader.readline()
                            if not h or h == b"\r\n":
                                break

                    # Notify client tunnel is ready
                    client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await client_writer.drain()

                    # Pipe bidirectional
                    await self._pipe_bidirectional(client_reader, client_writer, remote_reader, remote_writer)
                except Exception as e:
                    logger.debug("CONNECT tunnel error: %s", e)
                    client_writer.write(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
                    await client_writer.drain()

            else:
                # Standard HTTP GET/POST forward
                try:
                    remote_reader, remote_writer = await asyncio.open_connection(u_ip, u_port)
                    # Forward request line and headers
                    remote_writer.write(request_line)
                    for h in headers:
                        remote_writer.write(h)
                    remote_writer.write(b"\r\n")
                    await remote_writer.drain()

                    # Pipe bidirectional
                    await self._pipe_bidirectional(client_reader, client_writer, remote_reader, remote_writer)
                except Exception as e:
                    logger.debug("HTTP forward error: %s", e)
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()

        except Exception as e:
            logger.debug("Gateway client handler error: %s", e)
        finally:
            self.active_connections -= 1
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

    async def _connect_socks(self, proxy_ip: str, proxy_port: int, proto: str, target_host: str, target_port: int):
        """Perform SOCKS4/SOCKS5 handshake with upstream proxy."""
        reader, writer = await asyncio.open_connection(proxy_ip, proxy_port)
        if proto == "socks5":
            # SOCKS5 greeting: VER=5, NMETHODS=1, METHOD=0 (No Auth)
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            resp = await reader.readexactly(2)
            if resp != b"\x05\x00":
                raise ConnectionError("SOCKS5 auth negotiation failed")

            # SOCKS5 request: VER=5, CMD=1 (CONNECT), RSV=0, ATYP=3 (Domain), DOMAIN, PORT
            domain_bytes = target_host.encode("utf-8")
            req = b"\x05\x01\x00\x03" + bytes([len(domain_bytes)]) + domain_bytes + target_port.to_bytes(2, "big")
            writer.write(req)
            await writer.drain()
            resp = await reader.readexactly(4)
            if resp[1] != 0:
                raise ConnectionError(f"SOCKS5 connect failed code: {resp[1]}")
            # Read remainder of reply address
            atyp = resp[3]
            if atyp == 1:
                await reader.readexactly(4 + 2)
            elif atyp == 3:
                dlen = (await reader.readexactly(1))[0]
                await reader.readexactly(dlen + 2)
            elif atyp == 4:
                await reader.readexactly(16 + 2)

        elif proto == "socks4":
            import socket
            # Resolve target host to IPv4
            target_ip = socket.gethostbyname(target_host)
            ip_parts = [int(p) for p in target_ip.split(".")]
            # SOCKS4: VN=4, CD=1 (CONNECT), DSTPORT, DSTIP, NULL
            req = bytes([4, 1]) + target_port.to_bytes(2, "big") + bytes(ip_parts) + b"\x00"
            writer.write(req)
            await writer.drain()
            resp = await reader.readexactly(8)
            if resp[1] != 90:  # 90 = Request granted
                raise ConnectionError(f"SOCKS4 connect failed status: {resp[1]}")

        return reader, writer

    async def _pipe_bidirectional(self, r1: asyncio.StreamReader, w1: asyncio.StreamWriter,
                                  r2: asyncio.StreamReader, w2: asyncio.StreamWriter):
        async def forward(src_r, dst_w):
            try:
                while True:
                    data = await src_r.read(16384)
                    if not data:
                        break
                    dst_w.write(data)
                    await dst_w.drain()
            except Exception:
                pass
            finally:
                try:
                    dst_w.close()
                except Exception:
                    pass

        await asyncio.gather(forward(r1, w2), forward(r2, w1), return_exceptions=True)

    async def start(self):
        if not settings.GATEWAY_ENABLED:
            return
        self.server = await asyncio.start_server(
            self.handle_client,
            settings.GATEWAY_HOST,
            settings.GATEWAY_PORT
        )
        self.is_running = True
        logger.info("Rotating Proxy Gateway started on %s:%d (Strategy: %s)",
                    settings.GATEWAY_HOST, settings.GATEWAY_PORT, settings.GATEWAY_STRATEGY)

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        self.is_running = False

gateway = RotatingGateway()
