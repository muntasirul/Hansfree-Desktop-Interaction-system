"""
websocket_server.py — Python ↔ Chrome Extension Bridge

Runs a local WebSocket server on ws://localhost:9765
The Chrome extension connects to it automatically.

Responsibilities:
  - Receive page events from extension (scan complete, clicked, typed, etc.)
  - Send commands to extension (click N, type text, scroll, navigate)
  - Notify callbacks for overlay UI updates
"""

import asyncio
import json
import threading
import websockets
from typing import Callable, Optional


class WebSocketServer:
    """
    Async WebSocket server running in a background thread.

    Usage:
        server = WebSocketServer(on_event=..., on_connected=..., on_disconnected=...)
        server.start()                # non-blocking
        server.send_command(...)      # thread-safe
        server.stop()
    """

    HOST = "localhost"
    PORT = 9765

    def __init__(
        self,
        on_event:        Callable[[dict], None] = None,
        on_connected:    Callable[[], None] = None,
        on_disconnected: Callable[[], None] = None,
    ):
        self.on_event = on_event or (lambda d: print(f"[WS] Event: {d}"))
        self.on_connected = on_connected or (
            lambda: print("[WS] Extension connected"))
        self.on_disconnected = on_disconnected or (
            lambda: print("[WS] Extension disconnected"))

        self._loop:        Optional[asyncio.AbstractEventLoop] = None
        self._thread:      Optional[threading.Thread] = None
        self._websocket = None   # current connection
        self._stop_event = asyncio.Event()
        self._running = False

    # ── Public API (thread-safe) ───────────────────────────────────────────

    def start(self):
        """Start the WebSocket server in a background thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Shut down the server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def send_command(self, action: str, **kwargs):
        """
        Send a command to the Chrome extension (thread-safe).

        Examples:
            server.send_command("activate")
            server.send_command("click", num=5)
            server.send_command("type", text="hello")
            server.send_command("scroll", direction="down")
            server.send_command("navigate", cmd="back")
            server.send_command("open_url", url="https://youtube.com")
        """
        if not self._loop:
            print("[WS] Server not started yet")
            return

        payload = {"action": action, **kwargs}
        asyncio.run_coroutine_threadsafe(
            self._send(payload),
            self._loop
        )

    @property
    def is_connected(self) -> bool:
        return self._websocket is not None

    # ── Internals ──────────────────────────────────────────────────────────

    def _run_loop(self):
        """Create and run event loop in thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._running = True
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[WS] Server error: {e}")
        finally:
            self._loop.close()

    async def _serve(self):
        """Start the WebSocket server."""
        print(f"[WS] Listening on ws://{self.HOST}:{self.PORT}")
        try:
            async with websockets.serve(
                self._handler,
                self.HOST,
                self.PORT,
                ping_interval=20,
                ping_timeout=10,
            ):
                # Keep server alive until stop() is called
                while self._running:
                    await asyncio.sleep(0.5)
        except OSError as e:
            print(f"[WS] Cannot bind port {self.PORT}: {e}")

    async def _handler(self, websocket):
        """Handle a new extension connection."""
        print(f"[WS] Extension connected from {websocket.remote_address}")
        self._websocket = websocket
        self.on_connected()

        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    self.on_event(data)
                except json.JSONDecodeError:
                    print(f"[WS] Bad JSON: {raw[:100]}")
        except websockets.exceptions.ConnectionClosed:
            print("[WS] Extension disconnected")
        finally:
            self._websocket = None
            self.on_disconnected()

    async def _send(self, data: dict):
        """Send JSON data to the connected extension."""
        if self._websocket:
            try:
                await self._websocket.send(json.dumps(data))
            except Exception as e:
                print(f"[WS] Send error: {e}")
        else:
            print(
                f"[WS] No extension connected — buffering: {data.get('action')}")
