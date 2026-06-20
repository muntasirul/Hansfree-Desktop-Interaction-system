"""
main.py — Entry point for Typing Mode.

No overlay window — status and typed text are sent to the launcher's
WhisperBar overlay via a local UDP socket (port 19876).

The WhisperBar shows:
  • Purple dot + "Typing Mode active" when running
  • Each dictated phrase in purple text as it's typed
  • Voice commands (new line, delete that, etc.) briefly

Voice commands:
  "new line"                  → Enter
  "delete that"               → ctrl+backspace
  "scratch that"              → deletes last typed phrase
  "select all / copy / paste" → keyboard shortcuts
  "caps lock"                 → toggle ALL CAPS
  "pause typing"              → pause mic
  "stop typing"               → exit
"""

from typing_engine import TypingEngine
import os
import sys
import socket
import json
import threading
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── UDP connection to launcher WhisperBar ─────────────────────────────────────
LAUNCHER_UDP_PORT = 19876
_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _send(event: str, data: str):
    """Fire-and-forget UDP event to the launcher IPC listener."""
    try:
        msg = json.dumps({"event": event, "data": data}).encode("utf-8")
        _udp_sock.sendto(msg, ("127.0.0.1", LAUNCHER_UDP_PORT))
    except Exception:
        pass


def main():
    print("[TypingMode] Starting Typing Mode...")

    # Hidden root — keeps process alive for tkinter thread-safety
    root = tk.Tk()
    root.withdraw()
    root.title("Typing Mode")

    # ── Engine callbacks ──────────────────────────────────────────────────────
    def on_status(s: str):
        print(f"[TypingMode] {s}")
        _send("status", s)

    def on_text(t: str):
        print(f"[TypingMode] Typed: {t.strip()}")
        _send("typed", t.strip())

    def on_command(c: str):
        print(f"[TypingMode] Command: {c}")
        _send("command", c)

    def on_error(e: str):
        print(f"[TypingMode] Error: {e}")
        _send("status", f"Error: {e}")

    # ── Engine ────────────────────────────────────────────────────────────────
    engine = TypingEngine(
        on_status=on_status,
        on_text=on_text,
        on_command=on_command,
        on_error=on_error,
    )

    def _stop():
        print("[TypingMode] Stopping...")
        _send("status", "Stopped")
        engine.stop()
        try:
            root.after(200, root.destroy)
        except Exception:
            pass

    # ── Start engine ──────────────────────────────────────────────────────────
    threading.Thread(target=engine.run, daemon=True).start()
    print("[TypingMode] Running — speak to type. No overlay window.")

    # ── Keep process alive ────────────────────────────────────────────────────
    try:
        root.mainloop()
    except KeyboardInterrupt:
        _stop()

    print("[TypingMode] Exited.")


if __name__ == "__main__":
    main()
