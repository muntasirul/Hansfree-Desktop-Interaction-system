"""
overlay.py — Floating status overlay for Typing Mode.

A small always-on-top window that shows:
  • Microphone status (listening / processing / paused)
  • Last recognized text
  • Recent commands
  • Quick voice command cheat sheet
  • Pause / Stop buttons

Designed to be non-intrusive and accessible.
"""

import tkinter as tk
import tkinter.font as tkfont
import threading
import time


# ─────────────────────────────────────────────────────────────────────────────
#  Colors  (dark, accessible)
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg":           "#0d1117",
    "surface":      "#161b22",
    "border":       "#30363d",
    "text":         "#e6edf3",
    "text_dim":     "#8b949e",
    "green":        "#3fb950",
    "red":          "#f85149",
    "yellow":       "#d29922",
    "purple":       "#a371f7",
    "blue":         "#58a6ff",
    "cyan":         "#39d2c0",
}


class TypingOverlay(tk.Toplevel):
    """
    Floating always-on-top overlay window.

    Usage:
        overlay = TypingOverlay(root, on_pause=..., on_stop=...)
        overlay.set_status("Listening...")
        overlay.add_log("Hello world")
    """

    def __init__(self, master, on_pause=None, on_stop=None, on_resume=None):
        super().__init__(master)
        self._on_pause = on_pause or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_resume = on_resume or (lambda: None)
        self._is_paused = False
        self._is_minimized = False

        self._build_window()
        self._build_ui()
        self._start_pulse()

    # ── Window setup ─────────────────────────────────────────────────────────

    def _build_window(self):
        self.title("Typing Mode")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.overrideredirect(False)         # keep title bar for drag
        self.configure(bg=C["bg"])
        self.resizable(False, False)

        # Place at bottom-right of screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 380, 480
        x = sw - w - 20
        y = sh - h - 60
        self.geometry(f"{w}x{h}+{x}+{y}")

        # Allow dragging
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        x = self.winfo_x() + dx
        y = self.winfo_y() + dy
        self.geometry(f"+{x}+{y}")

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────
        title_bar = tk.Frame(self, bg=C["surface"], height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        tk.Label(
            title_bar, text="⌨️  Typing Mode",
            bg=C["surface"], fg=C["text"],
            font=("Segoe UI Semibold", 12),
        ).pack(side="left", padx=12, pady=8)

        # Minimize button
        tk.Button(
            title_bar, text="—", command=self._toggle_minimize,
            bg=C["surface"], fg=C["text_dim"],
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10), padx=6,
        ).pack(side="right", padx=4, pady=6)

        # ── Status indicator ───────────────────────────────────────────
        status_frame = tk.Frame(self, bg=C["bg"], pady=12)
        status_frame.pack(fill="x", padx=14)

        # Pulsing dot
        self.pulse_dot = tk.Label(
            status_frame, text="●",
            bg=C["bg"], fg=C["green"],
            font=("Segoe UI", 22),
        )
        self.pulse_dot.pack(side="left")

        status_right = tk.Frame(status_frame, bg=C["bg"])
        status_right.pack(side="left", padx=10)

        self.status_label = tk.Label(
            status_right, text="Initializing...",
            bg=C["bg"], fg=C["text"],
            font=("Segoe UI Semibold", 11),
            anchor="w",
        )
        self.status_label.pack(anchor="w")

        self.sub_status = tk.Label(
            status_right, text="Speak to type into any text field",
            bg=C["bg"], fg=C["text_dim"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.sub_status.pack(anchor="w")

        # ── Divider ────────────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Last typed ─────────────────────────────────────────────────
        typed_frame = tk.Frame(self, bg=C["bg"], pady=8)
        typed_frame.pack(fill="x", padx=14)

        tk.Label(
            typed_frame, text="LAST SPOKEN",
            bg=C["bg"], fg=C["text_dim"],
            font=("Segoe UI", 8), anchor="w",
        ).pack(anchor="w")

        self.typed_label = tk.Label(
            typed_frame, text="—",
            bg=C["surface"], fg=C["purple"],
            font=("Consolas", 11),
            anchor="w", wraplength=340,
            justify="left", padx=8, pady=6,
        )
        self.typed_label.pack(fill="x", pady=(2, 0))

        # ── Divider ────────────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Log (recent lines) ─────────────────────────────────────────
        log_header = tk.Frame(self, bg=C["bg"])
        log_header.pack(fill="x", padx=14, pady=(8, 0))

        tk.Label(
            log_header, text="RECENT",
            bg=C["bg"], fg=C["text_dim"],
            font=("Segoe UI", 8),
        ).pack(side="left")

        self.log_text = tk.Text(
            self, height=5, bg=C["surface"], fg=C["text"],
            font=("Consolas", 9), relief="flat",
            state="disabled", padx=8, pady=4,
            insertbackground=C["text"],
            wrap="word", cursor="arrow",
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(4, 8))

        # Tag colors
        self.log_text.tag_config("cmd",  foreground=C["cyan"])
        self.log_text.tag_config("txt",  foreground=C["text"])
        self.log_text.tag_config("err",  foreground=C["red"])
        self.log_text.tag_config("info", foreground=C["yellow"])

        # ── Divider ────────────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Cheat sheet ────────────────────────────────────────────────
        cheat_frame = tk.Frame(self, bg=C["bg"], pady=6)
        cheat_frame.pack(fill="x", padx=14)

        tk.Label(
            cheat_frame, text="VOICE COMMANDS",
            bg=C["bg"], fg=C["text_dim"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 4))

        commands = [
            ("period / comma / question mark",  "→ punctuation"),
            ("new line / enter",                 "→ line break"),
            ("delete that / scratch that",       "→ undo last phrase"),
            ("delete word",                      "→ ctrl+backspace"),
            ("select all / copy / paste",        "→ keyboard shortcuts"),
            ("caps lock",                        "→ toggle all caps"),
            ("pause typing / resume typing",     "→ pause/resume mic"),
            ("stop typing",                      "→ exit typing mode"),
        ]

        for cmd, desc in commands:
            row = tk.Frame(cheat_frame, bg=C["bg"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=cmd,  bg=C["bg"], fg=C["blue"],  font=(
                "Consolas", 8), width=32, anchor="w").pack(side="left")
            tk.Label(row, text=desc, bg=C["bg"], fg=C["text_dim"], font=(
                "Segoe UI", 8)).pack(side="left")

        # ── Divider ────────────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Control buttons ────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=C["bg"], pady=10)
        btn_frame.pack(fill="x", padx=14)

        self.pause_btn = tk.Button(
            btn_frame, text="⏸  Pause",
            command=self._toggle_pause,
            bg=C["yellow"], fg=C["bg"],
            relief="flat", cursor="hand2",
            font=("Segoe UI Semibold", 10),
            padx=16, pady=6,
        )
        self.pause_btn.pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frame, text="⏹  Stop",
            command=self._on_stop,
            bg=C["red"], fg=C["text"],
            relief="flat", cursor="hand2",
            font=("Segoe UI Semibold", 10),
            padx=16, pady=6,
        ).pack(side="left")

    # ── Public update methods ─────────────────────────────────────────────────

    def set_status(self, text: str, color: str = None):
        """Update the main status label."""
        self.status_label.configure(
            text=text,
            fg=color or C["text"],
        )
        # Auto-color based on content
        if "Listening" in text:
            self.pulse_dot.configure(fg=C["green"])
            self.status_label.configure(fg=C["green"])
        elif "Paused" in text:
            self.pulse_dot.configure(fg=C["yellow"])
            self.status_label.configure(fg=C["yellow"])
        elif "Processing" in text or "Typed" in text:
            self.pulse_dot.configure(fg=C["blue"])
            self.status_label.configure(fg=C["blue"])
        elif "Error" in text or "error" in text:
            self.pulse_dot.configure(fg=C["red"])
            self.status_label.configure(fg=C["red"])
        elif "Stopped" in text:
            self.pulse_dot.configure(fg=C["text_dim"])
            self.status_label.configure(fg=C["text_dim"])

    def set_last_typed(self, text: str):
        """Show the last typed text."""
        display = text.replace("\n", "↵").replace("\t", "→")
        self.typed_label.configure(text=display or "—")

    def add_log(self, text: str, tag: str = "txt"):
        """Add a line to the recent log."""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        line = f"{timestamp}  {text}\n"
        self.log_text.insert("end", line, tag)
        self.log_text.see("end")
        # Keep only last 100 lines
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 100:
            self.log_text.delete("1.0", "2.0")
        self.log_text.configure(state="disabled")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _toggle_pause(self):
        if self._is_paused:
            self._is_paused = False
            self.pause_btn.configure(text="⏸  Pause", bg=C["yellow"])
            self._on_resume()
        else:
            self._is_paused = True
            self.pause_btn.configure(text="▶  Resume", bg=C["green"])
            self._on_pause()

    def _toggle_minimize(self):
        """Minimize/restore the overlay."""
        if self._is_minimized:
            self.deiconify()
            self._is_minimized = False
        else:
            self.iconify()
            self._is_minimized = True

    def _start_pulse(self):
        """Animate the status dot."""
        self._pulse_state = True
        self._pulse()

    def _pulse(self):
        """Pulse the dot visibility."""
        if not self.winfo_exists():
            return
        current = self.pulse_dot.cget("fg")
        # Dim/bright cycle
        if self._pulse_state:
            alpha_color = self._dim_color(current)
            self.pulse_dot.configure(fg=alpha_color)
        else:
            # Restore (don't track full state, just re-apply from status)
            pass
        self._pulse_state = not self._pulse_state
        self.after(600, self._pulse)

    def _dim_color(self, hex_color: str) -> str:
        """Dim a hex color by blending toward bg."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            # Blend 40% toward bg (#0d1117)
            br, bg_, bb = 0x0d, 0x11, 0x17
            factor = 0.4
            r2 = int(r + (br - r) * factor)
            g2 = int(g + (bg_ - g) * factor)
            b2 = int(b + (bb - b) * factor)
            return f"#{r2:02x}{g2:02x}{b2:02x}"
        except:
            return hex_color
