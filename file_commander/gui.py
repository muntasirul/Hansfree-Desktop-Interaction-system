"""
gui.py — Main GUI for AI File Commander using CustomTkinter.
Dark, modern terminal-style interface with voice + text input.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import os
from pathlib import Path

from ai_handler import AIHandler
from file_ops import execute_action
from voice_handler import VoiceHandler

# ─────────────────────────────────────────────
#  Theme
# ─────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":          "#0d1117",
    "surface":     "#161b22",
    "surface2":    "#21262d",
    "border":      "#30363d",
    "accent":      "#388bfd",
    "accent_glow": "#1f6feb",
    "green":       "#3fb950",
    "red":         "#f85149",
    "yellow":      "#d29922",
    "text":        "#e6edf3",
    "text_dim":    "#8b949e",
    "mic_active":  "#f85149",
}

FONT_MONO  = ("Consolas", 13)
FONT_SMALL = ("Segoe UI", 11)
FONT_TITLE = ("Segoe UI Semibold", 14)
FONT_BIG   = ("Segoe UI Semibold", 22)


class FileCommanderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("AI File Commander")
        self.geometry("960x720")
        self.minsize(800, 600)
        self.configure(fg_color=COLORS["bg"])

        self.ai: AIHandler | None = None
        self.voice = VoiceHandler()
        self._pending_action: dict | None = None

        self._build_ui()
        self._try_init_ai()

    # ─────────────────────────────────────────
    #  UI Layout
    # ─────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="⚡ AI File Commander",
            font=ctk.CTkFont("Segoe UI Semibold", 20),
            text_color=COLORS["text"],
        ).pack(side="left", padx=24, pady=14)

        self.status_dot = ctk.CTkLabel(
            header, text="●", font=ctk.CTkFont("Segoe UI", 18),
            text_color=COLORS["green"]
        )
        self.status_dot.pack(side="right", padx=8)

        self.status_label = ctk.CTkLabel(
            header, text="Ready", font=ctk.CTkFont(*FONT_SMALL),
            text_color=COLORS["text_dim"]
        )
        self.status_label.pack(side="right", padx=4)

        # ── API Key row (shown if key missing) ──
        self.api_frame = ctk.CTkFrame(self, fg_color=COLORS["surface2"], corner_radius=0, height=48)
        self.api_frame.pack(fill="x")
        self.api_frame.pack_propagate(False)

        ctk.CTkLabel(self.api_frame, text="🔑 Groq API Key:",
                     font=ctk.CTkFont(*FONT_SMALL), text_color=COLORS["text_dim"]).pack(side="left", padx=12, pady=10)

        self.api_entry = ctk.CTkEntry(
            self.api_frame, placeholder_text="Paste your GRS_... key here...",
            show="*", width=380,
            fg_color=COLORS["surface"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=ctk.CTkFont(*FONT_MONO)
        )
        self.api_entry.pack(side="left", padx=8, pady=8)

        ctk.CTkButton(
            self.api_frame, text="Connect", width=100, height=30,
            fg_color=COLORS["accent_glow"], hover_color=COLORS["accent"],
            font=ctk.CTkFont(*FONT_SMALL), command=self._connect_api
        ).pack(side="left", padx=4)

        # ── Main columns ──
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        # ── Left: Chat log ──
        left = ctk.CTkFrame(main, fg_color=COLORS["surface"], corner_radius=10,
                            border_width=1, border_color=COLORS["border"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Command Log", font=ctk.CTkFont(*FONT_TITLE),
                     text_color=COLORS["text"]).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.log_box = ctk.CTkTextbox(
            left, fg_color=COLORS["bg"], text_color=COLORS["text"],
            font=ctk.CTkFont(*FONT_MONO), corner_radius=8,
            border_width=0, wrap="word", state="disabled"
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._configure_tags()

        # ── Right: File browser panel ──
        right = ctk.CTkFrame(main, fg_color=COLORS["surface"], corner_radius=10,
                             border_width=1, border_color=COLORS["border"])
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="File Browser", font=ctk.CTkFont(*FONT_TITLE),
                     text_color=COLORS["text"]).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        browse_row = ctk.CTkFrame(right, fg_color="transparent")
        browse_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        browse_row.columnconfigure(0, weight=1)

        self.path_var = tk.StringVar(value=str(Path.home()))
        path_entry = ctk.CTkEntry(browse_row, textvariable=self.path_var,
                                  fg_color=COLORS["surface2"], border_color=COLORS["border"],
                                  text_color=COLORS["text_dim"], font=ctk.CTkFont(*FONT_SMALL))
        path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        path_entry.bind("<Return>", lambda e: self._refresh_browser())

        ctk.CTkButton(browse_row, text="📂", width=36, height=30,
                      fg_color=COLORS["surface2"], hover_color=COLORS["border"],
                      command=self._browse_folder).grid(row=0, column=1)

        self.file_box = ctk.CTkTextbox(
            right, fg_color=COLORS["bg"], text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 11), corner_radius=8,
            border_width=0, wrap="none", state="disabled"
        )
        self.file_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._refresh_browser()

        # ── Bottom input bar ──
        bottom = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0,
                              border_width=1, border_color=COLORS["border"], height=70)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)
        bottom.columnconfigure(1, weight=1)

        self.mic_btn = ctk.CTkButton(
            bottom, text="🎙", width=54, height=46,
            fg_color=COLORS["surface2"], hover_color=COLORS["border"],
            font=ctk.CTkFont("Segoe UI Emoji", 22),
            corner_radius=10, command=self._start_voice
        )
        self.mic_btn.grid(row=0, column=0, padx=(14, 8), pady=12)

        self.cmd_entry = ctk.CTkEntry(
            bottom, placeholder_text="Type or speak a file command...",
            fg_color=COLORS["surface2"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=ctk.CTkFont(*FONT_MONO),
            height=46, corner_radius=10
        )
        self.cmd_entry.grid(row=0, column=1, sticky="ew", pady=12, padx=4)
        self.cmd_entry.bind("<Return>", lambda e: self._send_command())

        self.send_btn = ctk.CTkButton(
            bottom, text="Send ⏎", width=100, height=46,
            fg_color=COLORS["accent_glow"], hover_color=COLORS["accent"],
            font=ctk.CTkFont(*FONT_SMALL), corner_radius=10,
            command=self._send_command
        )
        self.send_btn.grid(row=0, column=2, padx=(4, 8), pady=12)

        self.clear_btn = ctk.CTkButton(
            bottom, text="Clear", width=70, height=46,
            fg_color=COLORS["surface2"], hover_color=COLORS["border"],
            text_color=COLORS["text_dim"], font=ctk.CTkFont(*FONT_SMALL),
            corner_radius=10, command=self._clear_log
        )
        self.clear_btn.grid(row=0, column=3, padx=(0, 14), pady=12)

    def _configure_tags(self):
        self.log_box.tag_config("user",    foreground=COLORS["accent"])
        self.log_box.tag_config("success", foreground=COLORS["green"])
        self.log_box.tag_config("error",   foreground=COLORS["red"])
        self.log_box.tag_config("warn",    foreground=COLORS["yellow"])
        self.log_box.tag_config("info",    foreground=COLORS["text_dim"])
        self.log_box.tag_config("action",  foreground="#c9d1d9")

    # ─────────────────────────────────────────
    #  AI init
    # ─────────────────────────────────────────

    def _try_init_ai(self):
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            try:
                self.ai = AIHandler()
                self.api_frame.pack_forget()
                self._set_status("Connected to Groq", COLORS["green"])
                self._log("info", f"✅ Groq AI connected ({self.ai.current_model}). Ready!\n")
                self._log("info", "💡 Try: \"copy all images from D:/photos to D:/backup\"\n")
                self._log("info", "💡 Or click 🎙 and speak your command.\n\n")
            except Exception as e:
                self._set_status("API key error", COLORS["red"])
                self._log("error", f"❌ Failed to connect: {e}\n")
        else:
            self._set_status("No API key", COLORS["yellow"])
            self._log("warn", "⚠️  No .env file found. Enter your Groq API key above.\n\n")

    def _connect_api(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showwarning("Missing Key", "Please enter your Groq API key.")
            return

        env_path = os.path.join(os.path.dirname(__file__), '.env')
        # Append or replace GROQ_API_KEY
        with open(env_path, 'w') as f:
            f.write(f"GROQ_API_KEY={key}\n")

        try:
            self.ai = AIHandler()
            self.api_frame.pack_forget()
            self._set_status("Connected to Groq", COLORS["green"])
            self._log("success", "✅ API key saved and Groq connected!\n\n")
        except Exception as e:
            self._log("error", f"❌ Connection failed: {e}\n")

    # ─────────────────────────────────────────
    #  Commands
    # ─────────────────────────────────────────

    def _send_command(self, text: str = ""):
        if not self.ai:
            messagebox.showwarning("Not Connected", "Please connect your Groq API key first.")
            return
        cmd = text or self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, "end")
        self._log("user", f"\n👤 You: {cmd}\n")
        self._set_status("Thinking...", COLORS["yellow"])
        self.send_btn.configure(state="disabled")
        threading.Thread(target=self._process_command, args=(cmd,), daemon=True).start()

    def _process_command(self, cmd: str):
        try:
            action = self.ai.parse_command(cmd)
            desc = action.get("description", "")
            self.after(0, self._log, "info", f"🤖 AI: {desc}\n")
            self.after(0, self._log, "action", f"   Action: {action.get('action', '?')} | "
                                                f"Source: {action.get('source', '—')} | "
                                                f"Dest: {action.get('destination', '—')} | "
                                                f"Filter: {action.get('filter', '*')}\n")

            if action.get("requires_confirmation"):
                self._pending_action = action
                self.after(0, self._ask_confirmation, desc)
            else:
                self.after(0, self._run_action, action)

        except Exception as e:
            self.after(0, self._log, "error", f"❌ Error: {e}\n")
            self.after(0, self._set_status, "Error", COLORS["red"])
            self.after(0, self.send_btn.configure, {"state": "normal"})

    def _ask_confirmation(self, desc: str):
        self._log("warn", f"⚠️  Destructive operation — confirming...\n")
        answer = messagebox.askyesno(
            "Confirm Action",
            f"Are you sure you want to:\n\n{desc}\n\nThis cannot be undone.",
            icon="warning"
        )
        if answer and self._pending_action:
            self._run_action(self._pending_action)
        else:
            self._log("warn", "🚫 Operation cancelled by user.\n")
            self._set_status("Cancelled", COLORS["yellow"])
            self.send_btn.configure(state="normal")
        self._pending_action = None

    def _run_action(self, action: dict):
        def _exec():
            ok, msg = execute_action(action)
            tag = "success" if ok else "error"
            self.after(0, self._log, tag, f"{msg}\n")
            status_text = "Done" if ok else "Failed"
            status_col = COLORS["green"] if ok else COLORS["red"]
            self.after(0, self._set_status, status_text, status_col)
            self.after(0, self.send_btn.configure, {"state": "normal"})
            # Refresh browser if a folder was involved
            src = action.get('source', '')
            dst = action.get('destination', '')
            if src or dst:
                self.after(100, self._refresh_browser)

        threading.Thread(target=_exec, daemon=True).start()

    # ─────────────────────────────────────────
    #  Voice
    # ─────────────────────────────────────────

    def _start_voice(self):
        if self.voice.is_listening:
            return
        self.mic_btn.configure(fg_color=COLORS["mic_active"], text="⏹")
        self._set_status("Listening...", COLORS["mic_active"])

        self.voice.listen_once(
            on_result=self._on_voice_result,
            on_error=self._on_voice_error,
            on_listening=lambda: self.after(0, self._log, "info", "\n🎙 Listening...\n")
        )

    def _on_voice_result(self, text: str):
        self.after(0, self.mic_btn.configure, {"fg_color": COLORS["surface2"], "text": "🎙"})
        self.after(0, self._log, "user", f"🎤 Voice: \"{text}\"\n")
        self.after(0, self._send_command, text)

    def _on_voice_error(self, msg: str):
        self.after(0, self.mic_btn.configure, {"fg_color": COLORS["surface2"], "text": "🎙"})
        self.after(0, self._log, "error", f"❌ Voice error: {msg}\n")
        self.after(0, self._set_status, "Voice error", COLORS["red"])

    # ─────────────────────────────────────────
    #  File browser panel
    # ─────────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.path_var.get())
        if folder:
            self.path_var.set(folder)
            self._refresh_browser()

    def _refresh_browser(self):
        path = self.path_var.get().strip()
        p = Path(path)
        self.file_box.configure(state="normal")
        self.file_box.delete("1.0", "end")

        if not p.exists():
            self.file_box.insert("end", f"Path not found:\n{path}")
            self.file_box.configure(state="disabled")
            return

        lines = [f"📁 {p}\n{'─'*40}\n"]
        try:
            items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for item in items:
                if item.is_dir():
                    lines.append(f"  📂 {item.name}/\n")
                else:
                    sz = item.stat().st_size
                    sz_str = f"{sz/1024:.1f}KB" if sz >= 1024 else f"{sz}B"
                    lines.append(f"  📄 {item.name}  ({sz_str})\n")
            lines.append(f"\n  {sum(1 for i in p.iterdir() if i.is_dir())} folder(s), "
                         f"{sum(1 for i in p.iterdir() if i.is_file())} file(s)")
        except PermissionError:
            lines.append("⚠️ Permission denied")

        self.file_box.insert("end", "".join(lines))
        self.file_box.configure(state="disabled")

    # ─────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────

    def _log(self, tag: str, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text, tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _set_status(self, text: str, color: str):
        self.status_label.configure(text=text)
        self.status_dot.configure(text_color=color)
