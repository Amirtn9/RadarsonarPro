"""WebSocket client pool for Sonar Radar.

Why this exists
--------------
The original project opened a new WebSocket connection per request. That is
slow and (more importantly) unstable behind NAT/CGNAT/firewalls, because idle
connections and repeated handshakes often fail.

This module provides a *persistent* connection pool per (ip, port, token).
Connections are kept open, protected by a per-connection lock (single in-flight
request per connection), and automatically reconnected on failure.

It is designed for the agent protocol used by `monitor_agent.py`:
  - first message: token (string)
  - next messages: JSON payloads
  - each payload -> one JSON response

The pool is safe to share across the whole bot.
"""

from __future__ import annotations

import atexit
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


logger = logging.getLogger(__name__)


try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    from websockets.exceptions import InvalidStatusCode
except Exception:  # pragma: no cover
    websockets = None
    ConnectionClosed = Exception
    InvalidStatusCode = Exception


Key = Tuple[str, int, str]


@dataclass
class _Conn:
    ws: Any
    key: Key
    created_at: float
    last_used_at: float
    lock: asyncio.Lock

    @property
    def is_open(self) -> bool:
        try:
            return self.ws and not getattr(self.ws, "closed", False)
        except Exception:
            return False


class WebSocketPool:
    """A small connection pool per (ip, port, token).

    Notes:
    - Each underlying websocket connection is used sequentially (send->recv)
      because the agent protocol is request/response without request_id.
    - Concurrency is achieved by having multiple connections per host.
    """

    def __init__(
        self,
        *,
        max_per_key: int = 3,
        open_timeout: float = 6.0,
        close_timeout: float = 6.0,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        max_size: Optional[int] = None,
        acquire_timeout: float = 30.0,
    ) -> None:
        self.max_per_key = int(max_per_key)
        self.open_timeout = float(open_timeout)
        self.close_timeout = float(close_timeout)
        self.ping_interval = float(ping_interval)
        self.ping_timeout = float(ping_timeout)
        self.max_size = max_size
        self.acquire_timeout = float(acquire_timeout)

        self._queues: Dict[Key, asyncio.LifoQueue[_Conn]] = {}
        self._counts: Dict[Key, int] = {}
        self._global_lock = asyncio.Lock()

        # best-effort cleanup on exit
        atexit.register(self._atexit_close)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    async def request(
        self,
        ip: str,
        port: int,
        token: str,
        payload: Dict[str, Any],
        *,
        timeout: float = 20.0,
        retries: int = 1,
    ) -> Dict[str, Any]:
        """Send one request and return parsed JSON response.

        `retries` is the number of reconnect retries (in addition to the first try).
        """

        if websockets is None:
            return {"error": "websockets library is not installed"}

        key: Key = (str(ip), int(port), str(token or ""))
        last_err: Optional[str] = None

        # Improved retry: exponential backoff with small jitter (stable under load)
        for attempt in range(retries + 1):
            conn: Optional[_Conn] = None
            try:
                conn = await self._acquire(key)
                async with conn.lock:
                    conn.last_used_at = time.time()
                    await conn.ws.send(json.dumps(payload))
                    raw = await asyncio.wait_for(conn.ws.recv(), timeout=timeout)
                    try:
                        return json.loads(raw)
                    except Exception:
                        return {"error": "invalid_json", "raw": raw}
            except asyncio.TimeoutError:
                last_err = "timeout"
                if conn:
                    await self._dispose(conn)
            except InvalidStatusCode as e:
                # Common misconfig: nginx / web server returns HTTP 200 instead of WS 101
                code = getattr(e, 'status_code', None)
                last_err = f"invalid_status_code: {code}"
                if int(code or 0) == 200:
                    logger.error(
                        "WS handshake got HTTP 200 (expected 101). "
                        "This usually means the WS reverse-proxy is misconfigured (e.g. nginx), "
                        "or you're connecting to the HTTP port instead of the websocket endpoint. "
                        "Check: Upgrade/Connection headers, proxy_http_version 1.1, and the ws location. "
                        "Target: ws://%s:%s",
                        ip,
                        port,
                    )
                else:
                    logger.error("WS handshake failed with HTTP status: %s", code)
                if conn:
                    await self._dispose(conn)
            except ConnectionClosed as e:
                last_err = f"connection_closed: {e}"
                if conn:
                    await self._dispose(conn)
            except OSError as e:
                last_err = f"os_error: {e}"
                if conn:
                    await self._dispose(conn)
            except Exception as e:
                last_err = f"ws_error: {e}"
                if conn:
                    await self._dispose(conn)
            finally:
                if conn and conn.is_open:
                    self._release(conn)

            # retry with exponential backoff (+ jitter)
            if attempt < retries:
                base = 0.35 * (2 ** attempt)
                # small deterministic jitter without random dependency
                jitter = (time.time() % 1.0) * 0.15
                await asyncio.sleep(min(6.0, base + jitter))

        return {"error": last_err or "unknown"}

    async def close_all(self) -> None:
        """Close all pooled connections."""
        if websockets is None:
            return
        async with self._global_lock:
            for key, q in list(self._queues.items()):
                while not q.empty():
                    try:
                        conn = q.get_nowait()
                    except Exception:
                        break
                    try:
                        await conn.ws.close()
                    except Exception:
                        pass
                self._queues.pop(key, None)
                self._counts.pop(key, None)

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------
    async def _acquire(self, key: Key) -> _Conn:
        """Get an existing open connection, create a new one, or wait.

        This function enforces `max_per_key` strictly.
        """

        async with self._global_lock:
            q = self._queues.get(key)
            if q is None:
                q = asyncio.LifoQueue()
                self._queues[key] = q
                self._counts[key] = 0

            # 1) Reuse idle connection if available
            try:
                conn = q.get_nowait()
                if conn and conn.is_open:
                    return conn
                # Closed connection in queue -> dispose (async) and continue.
                if conn:
                    asyncio.create_task(self._dispose(conn))
            except Exception:
                pass

            # 2) Create new connection if we are below max
            if self._counts.get(key, 0) < self.max_per_key:
                self._counts[key] = self._counts.get(key, 0) + 1
                create_new = True
            else:
                create_new = False

        if create_new:
            # connect outside global lock
            try:
                return await asyncio.wait_for(self._connect(key), timeout=self.acquire_timeout)
            except Exception:
                # rollback count on connect failure
                async with self._global_lock:
                    self._counts[key] = max(0, self._counts.get(key, 1) - 1)
                raise

        # 3) Pool is full -> wait for a connection to be released
        q = self._queues[key]
        conn = await asyncio.wait_for(q.get(), timeout=self.acquire_timeout)
        if conn and conn.is_open:
            return conn
        if conn:
            await self._dispose(conn)
        # retry
        return await self._acquire(key)

    def _release(self, conn: _Conn) -> None:
        q = self._queues.get(conn.key)
        if q is None:
            # pool was cleared; dispose
            asyncio.create_task(self._dispose(conn))
            return
        try:
            q.put_nowait(conn)
        except Exception:
            asyncio.create_task(self._dispose(conn))

    async def _dispose(self, conn: _Conn) -> None:
        """Close and decrement count."""
        try:
            if conn.ws and not getattr(conn.ws, "closed", False):
                await conn.ws.close()
        except Exception:
            pass
        async with self._global_lock:
            self._counts[conn.key] = max(0, self._counts.get(conn.key, 1) - 1)

    async def _connect(self, key: Key) -> _Conn:
        if websockets is None:
            raise RuntimeError("websockets library missing")

        ip, port, token = key
        uri = f"ws://{ip}:{port}"

        ws = await websockets.connect(
            uri,
            open_timeout=self.open_timeout,
            close_timeout=self.close_timeout,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            max_size=self.max_size,
        )

        # Send token once per connection.
        try:
            await ws.send(str(token))
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            raise

        now = time.time()
        return _Conn(ws=ws, key=key, created_at=now, last_used_at=now, lock=asyncio.Lock())

    def _atexit_close(self) -> None:
        # atexit can't await; best-effort synchronous close
        if websockets is None:
            return
        try:
            loop = asyncio.get_event_loop()
        except Exception:
            return

        if loop.is_closed():
            return

        async def _close():
            await self.close_all()

        try:
            if loop.is_running():
                # schedule and return
                loop.create_task(_close())
            else:
                loop.run_until_complete(_close())
        except Exception:
            pass


# A single shared pool for the whole application.
# Values are read from settings.py (and can be overridden via sonar_config.json / env).
try:
    from settings import (
        WS_POOL_MAX_PER_KEY,
        WS_OPEN_TIMEOUT,
        WS_CLOSE_TIMEOUT,
        WS_PING_INTERVAL,
        WS_PING_TIMEOUT,
        WS_MAX_MESSAGE_SIZE,
        WS_ACQUIRE_TIMEOUT,
    )

    GLOBAL_WS_POOL = WebSocketPool(
        max_per_key=WS_POOL_MAX_PER_KEY,
        open_timeout=WS_OPEN_TIMEOUT,
        close_timeout=WS_CLOSE_TIMEOUT,
        ping_interval=WS_PING_INTERVAL,
        ping_timeout=WS_PING_TIMEOUT,
        max_size=WS_MAX_MESSAGE_SIZE,
        acquire_timeout=WS_ACQUIRE_TIMEOUT,
    )
except Exception:
    # Fallback defaults
    GLOBAL_WS_POOL = WebSocketPool()


async def reconnect_all() -> None:
    """Force-close all pooled sockets so next request reconnects."""
    try:
        await GLOBAL_WS_POOL.close_all()
    except Exception:
        pass
