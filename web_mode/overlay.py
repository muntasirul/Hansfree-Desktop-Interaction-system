"""
overlay.py — Floating Status Overlay for Web Mode
"""

import tkinter as tk
import time


C = {
    "bg":        "#0a0e14",
    "surface":   "#0d1420",
    "surface2":  "#121920",
    "border":    "#1e2d40",
    "text":      "#e6edf3",
    "text_dim":  "#8b949e",
    "text_muted": "#484f58",
    "cyan":      "#00d4ff",
    "green":     "#3fb950",
    "red":       "#f85149",
    "yellow":    "#d29922",
    "purple":    "#cc88ff",
}


class WebModeOverlay(tk.Toplevel):
    def __init__(self, master, on_pause=None, on_stop=None, on_rescan=None, on_resume=None):
        super().__init__(master)
        self._on_pause = on_pause or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_rescan = on_rescan or (lambda: None)
        self._on_resume = on_resume or (lambda: None)
        self._paused = False
        self._dx = self._dy = 0

        self._setup_window()
        self._build_ui()
        self._start_pulse()

    def _setup_window(self):
        self.title("Web Mode")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.94)
        self.configure(bg=C["bg"])
        self.resizable(False, False)

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 360, 560
        self.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 60}")

        self.bind("<ButtonPress-1>",
                  lambda e: (setattr(self, '_dx', e.x), setattr(self, '_dy', e.y)))
        self.bind("<B1-Motion>",
                  lambda e: self.geometry(
                      f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}"))

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=C["surface2"], height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="🌐  WEB MODE", bg=C["surface2"], fg=C["cyan"],
                 font=("Courier New", 12, "bold")).pack(side="left", padx=12, pady=10)

        conn_frame = tk.Frame(hdr, bg=C["surface2"])
        conn_frame.pack(side="right", padx=12)
        self.conn_dot = tk.Label(conn_frame, text="●", bg=C["surface2"],
                                 fg=C["red"], font=("Segoe UI", 10))
        self.conn_dot.pack(side="left")
        self.conn_label = tk.Label(conn_frame, text="Disconnected",
                                   bg=C["surface2"], fg=C["text_dim"],
                                   font=("Courier New", 9))
        self.conn_label.pack(side="left", padx=(4, 0))

        # Status row
        stat_frame = tk.Frame(self, bg=C["bg"], pady=10)
        stat_frame.pack(fill="x", padx=14)

        self.pulse_dot = tk.Label(stat_frame, text="●", bg=C["bg"],
                                  fg=C["green"], font=("Segoe UI", 20))
        self.pulse_dot.pack(side="left")

        stat_right = tk.Frame(stat_frame, bg=C["bg"])
        stat_right.pack(side="left", padx=10)

        self.status_label = tk.Label(stat_right, text="Initializing...",
                                     bg=C["bg"], fg=C["text"],
                                     font=("Segoe UI Semibold", 11), anchor="w")
        self.status_label.pack(anchor="w")

        self.page_label = tk.Label(stat_right, text="No page loaded",
                                   bg=C["bg"], fg=C["text_dim"],
                                   font=("Segoe UI", 9), anchor="w")
        self.page_label.pack(anchor="w")

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Last speech
        sp_frame = tk.Frame(self, bg=C["bg"], pady=8)
        sp_frame.pack(fill="x", padx=14)
        tk.Label(sp_frame, text="HEARD", bg=C["bg"], fg=C["text_muted"],
                 font=("Courier New", 8)).pack(anchor="w")
        self.speech_label = tk.Label(sp_frame, text="—",
                                     bg=C["surface"], fg=C["cyan"],
                                     font=("Courier New", 11),
                                     anchor="w", wraplength=320,
                                     justify="left", padx=8, pady=5)
        self.speech_label.pack(fill="x", pady=(3, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Log
        log_hdr = tk.Frame(self, bg=C["bg"])
        log_hdr.pack(fill="x", padx=14, pady=(8, 2))
        tk.Label(log_hdr, text="ACTIONS", bg=C["bg"], fg=C["text_muted"],
                 font=("Courier New", 8)).pack(side="left")

        self.log = tk.Text(self, height=6, bg=C["surface"], fg=C["text"],
                           font=("Courier New", 9), relief="flat",
                           state="disabled", padx=8, pady=4,
                           insertbackground=C["text"], wrap="word", cursor="arrow")
        self.log.pack(fill="both", padx=14, pady=(0, 8))
        self.log.tag_config("action", foreground=C["green"])
        self.log.tag_config("nav",    foreground=C["cyan"])
        self.log.tag_config("type",   foreground=C["purple"])
        self.log.tag_config("err",    foreground=C["red"])
        self.log.tag_config("info",   foreground=C["yellow"])

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Cheat sheet
        cheat = tk.Frame(self, bg=C["bg"], pady=8)
        cheat.pack(fill="x", padx=14)
        tk.Label(cheat, text="VOICE COMMANDS", bg=C["bg"], fg=C["text_muted"],
                 font=("Courier New", 8)).pack(anchor="w", pady=(0, 4))

        cmds = [
            ('"5" / "click 5"',      "→ click element #5"),
            ('"scroll down/up"',     "→ scroll page"),
            ('"go back/forward"',    "→ browser history"),
            ('"new tab"',            "→ open new tab"),
            ('"youtube dot com"',    "→ open URL"),
            ('"how to bake cake"',   "→ Google search"),
            ('"enter"',              "→ submit form"),
            ('"rescan"',             "→ refresh numbers"),
        ]
        for voice, action in cmds:
            row = tk.Frame(cheat, bg=C["bg"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=voice,  bg=C["bg"], fg=C["cyan"],
                     font=("Courier New", 8), width=22, anchor="w").pack(side="left")
            tk.Label(row, text=action, bg=C["bg"], fg=C["text_dim"],
                     font=("Courier New", 8)).pack(side="left")

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Buttons
        btn_row = tk.Frame(self, bg=C["bg"], pady=10)
        btn_row.pack(fill="x", padx=14)

        self.pause_btn = tk.Button(btn_row, text="⏸ Pause",
                                   command=self._toggle_pause,
                                   bg=C["yellow"], fg=C["bg"],
                                   relief="flat", cursor="hand2",
                                   font=("Segoe UI Semibold", 10),
                                   padx=14, pady=5)
        self.pause_btn.pack(side="left", padx=(0, 6))

        tk.Button(btn_row, text="🔄 Rescan", command=self._on_rescan,
                  bg=C["cyan"], fg=C["bg"], relief="flat", cursor="hand2",
                  font=("Segoe UI Semibold", 10), padx=14, pady=5
                  ).pack(side="left", padx=(0, 6))

        tk.Button(btn_row, text="⏹ Stop", command=self._on_stop,
                  bg=C["red"], fg=C["text"], relief="flat", cursor="hand2",
                  font=("Segoe UI Semibold", 10), padx=14, pady=5
                  ).pack(side="left")

    # ── Public methods ──────────────────────────────────────────────────────

    def set_connected(self, connected: bool):
        col = C["green"] if connected else C["red"]
        txt = "Connected" if connected else "Disconnected"
        self.conn_dot.configure(fg=col)
        self.conn_label.configure(text=txt, fg=col)

    def set_status(self, text: str):
        self.status_label.configure(text=text)
        if "Listening" in text:
            self.pulse_dot.configure(fg=C["green"])
        elif "Paused" in text:
            self.pulse_dot.configure(fg=C["yellow"])
        elif "Error" in text or "error" in text:
            self.pulse_dot.configure(fg=C["red"])
        else:
            self.pulse_dot.configure(fg=C["cyan"])

    def set_page(self, title: str, url: str = ""):
        short = (url[:42] + "...") if len(url) > 42 else url
        self.page_label.configure(text=f"{title[:32]}  {short}")

    def set_last_speech(self, text: str):
        self.speech_label.configure(text=text or "—")

    def add_log(self, text: str, tag: str = "info"):
        self.log.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"{ts}  {text}\n", tag)
        self.log.see("end")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 200:
            self.log.delete("1.0", "2.0")
        self.log.configure(state="disabled")

    # ── Internal ────────────────────────────────────────────────────────────

    def _toggle_pause(self):
        if self._paused:
            self._paused = False
            self.pause_btn.configure(text="⏸ Pause", bg=C["yellow"])
            self._on_resume()
        else:
            self._paused = True
            self.pause_btn.configure(text="▶ Resume", bg=C["green"])
            self._on_pause()

    def _start_pulse(self):
        self._pulse_state = True
        self._do_pulse()

    def _do_pulse(self):
        if not self.winfo_exists():
            return
        # Simple blink
        current = self.pulse_dot.cget("fg")
        if self._pulse_state:
            self.pulse_dot.configure(fg=C["bg"])
        else:
            self.pulse_dot.configure(
                fg=current if current != C["bg"] else C["green"])
        self._pulse_state = not self._pulse_state
        self.after(600, self._do_pulse)
