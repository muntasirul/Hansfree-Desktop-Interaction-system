"""
main.py — Entry point for Web Mode.

No overlay window — all status updates go to the launcher's WhisperBar
via UDP port 19877 (typing mode uses 19876).

The WhisperBar shows:
  • Cyan dot when web mode is active
  • What voice commands were heard
  • Page title and navigation events

Startup sequence:
  1. Start WebSocket server (ws://localhost:9765)
  2. Start voice recognition loop
  3. Send status events to launcher WhisperBar via UDP
  4. Commands flow: Voice → Parser → WebSocket → Extension → Browser
"""

from voice_handler import WebVoiceHandler
from websocket_server import WebSocketServer
import os
import sys
import socket
import json
import threading
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── UDP → launcher WhisperBar ─────────────────────────────────────────────────
WEB_UDP_PORT = 19877
_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _send(event: str, data: str):
    """Fire-and-forget event to launcher's WhisperBar."""
    try:
        msg = json.dumps(
            {"event": event, "data": data, "source": "web"}).encode()
        _udp_sock.sendto(msg, ("127.0.0.1", WEB_UDP_PORT))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  WebMode Controller
# ─────────────────────────────────────────────────────────────────────────────

class WebModeController:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._active = False

        # ── WebSocket server ──────────────────────────────────────────────────
        self.ws = WebSocketServer(
            on_event=self._on_extension_event,
            on_connected=self._on_ext_connected,
            on_disconnected=self._on_ext_disconnected,
        )

        # ── Voice handler ─────────────────────────────────────────────────────
        self.voice = WebVoiceHandler(
            on_click=self._handle_click,
            on_type=self._handle_type,
            on_navigate=self._handle_navigate,
            on_command=self._handle_command,
            on_status=lambda s: _send("status", s),
            on_error=lambda e: _send("error", e),
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._active = True
        self.ws.start()
        self.voice.start()
        _send("status", "🔌 Waiting for Chrome extension...")
        _send("web_started", "")
        self.ws.send_command("activate")

    def stop(self):
        self._active = False
        self.voice.stop()
        self.ws.send_command("deactivate")
        self.ws.stop()
        _send("status", "⏹ Web Mode stopped")
        _send("web_stopped", "")
        try:
            self.root.after(400, self.root.destroy)
        except Exception:
            pass

    # ── Voice command handlers ─────────────────────────────────────────────────

    def _handle_click(self, num: int):
        self.ws.send_command("click", num=num)
        _send("heard", f"click {num}")

    def _handle_type(self, text: str):
        self.ws.send_command("type", text=text)
        _send("typed", text)

    def _handle_navigate(self, url: str):
        self.ws.send_command("open_url", url=url)
        _send("heard", f"→ {url}")

    def _handle_command(self, cmd: str):
        if cmd == "stop":
            self.stop()
            return

        dispatch = {
            "scroll_down": lambda: self.ws.send_command("scroll", direction="down"),
            "scroll_up": lambda: self.ws.send_command("scroll", direction="up"),
            "scroll_left": lambda: self.ws.send_command("scroll", direction="left"),
            "scroll_right": lambda: self.ws.send_command("scroll", direction="right"),
            "scroll_top": lambda: self.ws.send_command("scroll", direction="top"),
            "scroll_bottom": lambda: self.ws.send_command("scroll", direction="bottom"),
            "go_back": lambda: self.ws.send_command("navigate", cmd="back"),
            "go_forward": lambda: self.ws.send_command("navigate", cmd="forward"),
            "refresh": lambda: self.ws.send_command("navigate", cmd="refresh"),
            "new_tab": lambda: self.ws.send_command("navigate", cmd="new_tab"),
            "close_tab": lambda: self.ws.send_command("navigate", cmd="close_tab"),
            "next_tab": lambda: self.ws.send_command("navigate", cmd="next_tab"),
            "prev_tab": lambda: self.ws.send_command("navigate", cmd="prev_tab"),
            "enter": lambda: self.ws.send_command("enter"),
            "clear_input": lambda: self.ws.send_command("clear"),
            "rescan": lambda: self.ws.send_command("rescan"),
            "media_pause": lambda: self.ws.send_command("media_toggle"),
            "media_play": lambda: self.ws.send_command("media_toggle"),
            "media_mute": lambda: self.ws.send_command("media_mute"),
            "media_vol_up": lambda: self.ws.send_command("media_vol", direction="up"),
            "media_vol_down": lambda: self.ws.send_command("media_vol", direction="down"),
            "media_fullscreen": lambda: self.ws.send_command("media_fullscreen"),
            "media_reveal": lambda: self.ws.send_command("media_reveal"),
        }

        action = dispatch.get(cmd)
        if action:
            action()
            _send("heard", cmd.replace("_", " "))
        else:
            print(f"[WebMode] Unknown command: {cmd}")

    # ── Extension event handlers ───────────────────────────────────────────────

    def _on_ext_connected(self):
        _send("status", "🎙 Listening...")
        _send("connected", "Chrome extension connected")
        self.ws.send_command("activate")

    def _on_ext_disconnected(self):
        _send("status", "🔌 Extension disconnected")

    def _on_extension_event(self, event: dict):
        etype = event.get("type", "")

        if etype == "scan_complete":
            count = event.get("count", 0)
            title = event.get("title", "")
            _send("page", f"🔢 {count} labels — {title[:40]}")

        elif etype == "page_loaded":
            title = event.get("title", "")
            url = event.get("url", "")
            _send("page", f"📄 {title[:40]}")

        elif etype == "typing_mode_entered":
            label = event.get("element", "")
            _send("status", f"⌨ Typing into: {label[:30]}")
            # tells launcher to show typing indicator
            _send("web_typing", label)
            self.voice.set_typing_mode(True)

        elif etype == "tab_changed":
            title = event.get("title", "")
            _send("page", f"⇥ {title[:40]}")

        elif etype == "extension_connected":
            self._on_ext_connected()

        elif etype == "error":
            _send("error", event.get("message", ""))


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("[WebMode] Starting...")

    root = tk.Tk()
    root.withdraw()

    controller = WebModeController(root)
    controller.start()

    print("[WebMode] Running. No overlay window — status shows in WhisperBar.")
    print("[WebMode] WebSocket on ws://localhost:9765")

    try:
        root.mainloop()
    except KeyboardInterrupt:
        controller.stop()

    print("[WebMode] Exited.")


if __name__ == "__main__":
    main()
