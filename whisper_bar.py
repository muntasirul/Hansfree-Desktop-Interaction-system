"""
whisper_bar.py — Slim always-on-top overlay that shows what Whisper heard.

Appears at the top-center of the screen on launcher startup.
Shows the last transcribed phrase with a mic status dot.

Usage (from launcher):
    bar = WhisperBar(root)
    bar.show_heard("start cursor mode")   # called from voice_mode_activator
    bar.set_listening(True)               # mic open
    bar.set_listening(False)              # mic closed / processing
"""

import tkinter as tk
import threading
import time


# ── Theme (matches launcher dark theme) ──────────────────────────────────────
C = {
    "bg":       "#0d1117",
    "surface":  "#161b22",
    "border":   "#30363d",
    "text":     "#e6edf3",
    "dim":      "#8b949e",
    "green":    "#3fb950",
    "yellow":   "#d29922",
    "blue":     "#58a6ff",
    "cyan":     "#39d2c0",
    "red":      "#f85149",
    "purple":   "#a371f7",
}

# How long the heard-text stays visible before fading to placeholder (ms)
CLEAR_AFTER_MS = 4000


class WhisperBar(tk.Toplevel):
    """
    Slim horizontal bar — always on top, top-center of screen.
    Non-intrusive: 480 × 46 px, semi-transparent, no title bar.

    States:
      Listening  — green dot  + "Listening…" dim placeholder
      Processing — yellow dot + last phrase shown in bright text
      Heard      — blue dot   + transcription displayed
    """

    def __init__(self, master):
        super().__init__(master)

        self._clear_timer: threading.Timer = None
        self._pulse_on = True
        self._typing_active = False

        self._build_window()
        self._build_ui()
        self._start_pulse()

        # Show "ready" state immediately
        self.set_listening(True)

    # ── Typing Mode integration ──────────────────────────────────────────────

    def set_typing_mode(self, active: bool):
        """
        Called by launcher when typing mode starts or stops.
        Purple dot + wider bar while active.
        Thread-safe.
        """
        self._safe(self._set_typing_mode_ui, active)

    def show_typed(self, text: str):
        """
        Display dictated text in purple — distinct from voice commands.
        Thread-safe.
        """
        self._safe(self._display_typed, text)

    def _set_typing_mode_ui(self, active: bool):
        self._typing_active = active
        if active:
            self.dot.configure(fg=C["purple"])
            self.heard_label.configure(
                text="⌨ Typing Mode active — speak to type", fg=C["purple"])
            # Widen bar to fit longer dictation text
            sw = self.winfo_screenwidth()
            w = 640
            x = (sw - w) // 2
            y = self.winfo_y()
            self.geometry(f"{w}x46+{x}+{y}")
        else:
            # Restore normal width and state
            sw = self.winfo_screenwidth()
            w = 480
            x = (sw - w) // 2
            y = self.winfo_y()
            self.geometry(f"{w}x46+{x}+{y}")
            self._reset_placeholder()

    def _display_typed(self, text: str):
        """Show dictated text in purple, auto-clear after 5s."""
        if self._clear_timer:
            self._clear_timer.cancel()
            self._clear_timer = None

        display = text.strip()
        if len(display) > 68:
            display = display[:65] + "…"

        self.heard_label.configure(text=f"⌨ {display}", fg=C["purple"])
        self.dot.configure(fg=C["purple"])

        self._clear_timer = threading.Timer(
            5.0, lambda: self._safe(self._reset_typing_placeholder))
        self._clear_timer.daemon = True
        self._clear_timer.start()

    def _reset_typing_placeholder(self):
        """After auto-clear, go back to typing-active placeholder."""
        if self._typing_active:
            self.heard_label.configure(
                text="⌨ Typing Mode active — speak to type", fg=C["purple"])
            self.dot.configure(fg=C["purple"])
        else:
            self._reset_placeholder()

    # ── Web Mode integration ─────────────────────────────────────────────────

    def set_web_mode(self, active: bool):
        """Cyan dot when web mode is active. Thread-safe."""
        self._safe(self._set_web_mode_ui, active)

    def show_web_event(self, text: str):
        """Show a web mode event (page title, command heard). Thread-safe."""
        self._safe(self._display_web_event, text)

    def _set_web_mode_ui(self, active: bool):
        if active:
            self.dot.configure(fg=C["cyan"])
            self.heard_label.configure(
                text="🌐 Web Mode active — speak commands", fg=C["cyan"])
        else:
            self._reset_placeholder()

    def _display_web_event(self, text: str):
        """Show web event in cyan, auto-clear after 4s."""
        if self._clear_timer:
            self._clear_timer.cancel()
            self._clear_timer = None
        display = text.strip()
        if len(display) > 68:
            display = display[:65] + "…"
        self.heard_label.configure(text=display, fg=C["cyan"])
        self.dot.configure(fg=C["cyan"])
        self._clear_timer = threading.Timer(
            4.0, lambda: self._safe(self._reset_web_placeholder))
        self._clear_timer.daemon = True
        self._clear_timer.start()

    def _reset_web_placeholder(self):
        # Keep cyan if web mode still active (tracked by launcher)
        # Just reset text to the active placeholder
        self.heard_label.configure(
            text="🌐 Web Mode active — speak commands", fg=C["cyan"])
        self.dot.configure(fg=C["cyan"])

    # ── Window ────────────────────────────────────────────────────────────────

    def _build_window(self):
        self.overrideredirect(True)          # no title bar, no borders
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=C["bg"])
        self.resizable(False, False)

        # Position: top-center of screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        w, h = 480, 46
        x = (sw - w) // 2
        y = 18                             # small gap from top edge
        self.geometry(f"{w}x{h}+{x}+{y}")

        # Drag to reposition
        self.bind("<ButtonPress-1>",   self._drag_start)
        self.bind("<B1-Motion>",       self._drag_move)
        # Double-click to hide/show
        self.bind("<Double-Button-1>", self._toggle_minimize)
        self._minimized = False

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        x = self.winfo_x() + (e.x - self._dx)
        y = self.winfo_y() + (e.y - self._dy)
        self.geometry(f"+{x}+{y}")

    def _toggle_minimize(self, _=None):
        if self._minimized:
            self.deiconify()
            self._minimized = False
        else:
            self.iconify()
            self._minimized = True

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Thin coloured top border
        tk.Frame(self, bg=C["cyan"], height=2).pack(fill="x", side="top")

        # Main row
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="both", expand=True, padx=10)

        # Pulsing status dot
        self.dot = tk.Label(
            row, text="●", bg=C["bg"], fg=C["green"],
            font=("Segoe UI", 13),
        )
        self.dot.pack(side="left", padx=(0, 6))

        # "WHISPER" label
        tk.Label(
            row, text="WHISPER", bg=C["bg"], fg=C["dim"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 8))

        # Divider
        tk.Frame(row, bg=C["border"], width=1, height=24).pack(
            side="left", padx=(0, 10))

        # Transcription text
        self.heard_label = tk.Label(
            row, text="Listening…",
            bg=C["bg"], fg=C["dim"],
            font=("Consolas", 11),
            anchor="w",
        )
        self.heard_label.pack(side="left", fill="x", expand=True)

        # Tiny hint on right
        tk.Label(
            row, text="drag to move  •  dbl-click to hide",
            bg=C["bg"], fg=C["border"],
            font=("Segoe UI", 7),
        ).pack(side="right", padx=(6, 0))

    # ── Public API ────────────────────────────────────────────────────────────

    def show_heard(self, text: str):
        """
        Display what Whisper just transcribed.
        Called from voice_mode_activator after each recognition.
        Thread-safe — can be called from any thread.
        """
        self._safe(self._display_heard, text)

    def set_listening(self, listening: bool):
        """
        True  → green dot, dim 'Listening…' placeholder
        False → yellow dot, 'Processing…'
        Thread-safe.
        """
        self._safe(self._set_listening_ui, listening)

    def set_status(self, text: str, color: str = None):
        """Show arbitrary status text (e.g. 'Model loading…')."""
        self._safe(self._set_status_ui, text, color or C["dim"])

    # ── Internal UI updates (must run on main thread) ─────────────────────────

    def _display_heard(self, text: str):
        """Show transcription in bright text, auto-clear after CLEAR_AFTER_MS."""
        # Cancel previous clear timer
        if self._clear_timer:
            self._clear_timer.cancel()
            self._clear_timer = None

        display = text.strip()
        if len(display) > 52:
            display = display[:49] + "…"

        self.heard_label.configure(text=f'"{display}"', fg=C["text"])
        self.dot.configure(fg=C["blue"])

        # Schedule auto-clear back to placeholder
        self._clear_timer = threading.Timer(
            CLEAR_AFTER_MS / 1000, lambda: self._safe(self._reset_placeholder))
        self._clear_timer.daemon = True
        self._clear_timer.start()

    def _set_listening_ui(self, listening: bool):
        if listening:
            self.dot.configure(fg=C["green"])
            # Only reset text if nothing important is showing
            if self.heard_label.cget("fg") != C["text"]:
                self.heard_label.configure(text="Listening…", fg=C["dim"])
        else:
            self.dot.configure(fg=C["yellow"])
            if self.heard_label.cget("fg") != C["text"]:
                self.heard_label.configure(text="Processing…", fg=C["dim"])

    def _set_status_ui(self, text: str, color: str):
        self.heard_label.configure(text=text, fg=color)

    def _reset_placeholder(self):
        self.heard_label.configure(text="Listening…", fg=C["dim"])
        self.dot.configure(fg=C["green"])

    # ── Pulse animation ───────────────────────────────────────────────────────

    def _start_pulse(self):
        self._pulse()

    def _pulse(self):
        if not self.winfo_exists():
            return
        try:
            current = self.dot.cget("fg")
            # Pulse green when listening, pulse purple when typing
            if current == C["green"] and not self._typing_active:
                dimmed = self._dim(current)
                self.dot.configure(fg=dimmed if self._pulse_on else C["green"])
            elif current == C["purple"] and self._typing_active:
                dimmed = self._dim(current)
                self.dot.configure(
                    fg=dimmed if self._pulse_on else C["purple"])
            self._pulse_on = not self._pulse_on
        except Exception:
            pass
        self.after(700, self._pulse)

    def _dim(self, hex_color: str) -> str:
        """Blend color 50% toward background for pulse effect."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            br, bg_, bb = 0x0d, 0x11, 0x17
            f = 0.5
            return f"#{int(r+(br-r)*f):02x}{int(g+(bg_-g)*f):02x}{int(b+(bb-b)*f):02x}"
        except Exception:
            return hex_color

    # ── Thread-safety helper ──────────────────────────────────────────────────

    def _safe(self, fn, *args):
        """Schedule a UI function on the tkinter main thread."""
        try:
            if self.winfo_exists():
                self.after(0, fn, *args)
        except Exception:
            pass
