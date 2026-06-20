"""
launcher.py — Central Hub for Desktop Navigation System.
Launch all 4 modes from a single premium dark interface.
Voice commands to activate modes + AI Assistant.

Run:  python launcher.py
"""
from file_commander.file_ops import execute_action
from file_commander.voice_handler import VoiceHandler
from file_commander.ai_handler import AIHandler
import customtkinter as ctk
import subprocess
import threading
import socket
import json as _json
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from voice_mode_activator import VoiceModeActivator
from whisper_bar import WhisperBar
from focus_watcher import FocusWatcher
from assistant import get_assistant
import sys
import os

# Add file_commander to path FIRST, before any imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'file_commander'))


# Add file_commander to path FIRST, before any imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'file_commander'))

# Now import from file_commander modules

# Standard imports

# Local imports


# ─────────────────────────────────────────────────────────────────────────────
#  Theme & Constants
# ─────────────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":           "#0a0e14",
    "surface":      "#121920",
    "surface2":     "#1a222c",
    "border":       "#2a3444",
    "accent":       "#388bfd",
    "accent_glow":  "#1f6feb",
    "green":        "#3fb950",
    "green_dim":    "#1a3a28",
    "red":          "#f85149",
    "red_dim":      "#3d1a1a",
    "yellow":       "#d29922",
    "yellow_dim":   "#3d2e10",
    "purple":       "#a371f7",
    "purple_dim":   "#2d1f4e",
    "cyan":         "#39d2c0",
    "cyan_dim":     "#163832",
    "text":         "#e6edf3",
    "text_dim":     "#6e7681",
    "text_muted":   "#484f58",
}

# Card configurations for each mode
MODE_CARDS = [
    {
        "id":          "cursor",
        "title":       "Cursor Navigation",
        "subtitle":    "Head & Nose Tracking",
        "icon":        "🎯",
        "description": "Control your cursor with nose movement.\nBlink to click, mouth to interact.",
        "color":       COLORS["accent"],
        "color_dim":   "#152238",
        "enabled":     True,
        "script_dir":  "Cursor",
        "script":      "gesture_pilot.py",
    },
    {
        "id":          "typing",
        "title":       "Typing Mode",
        "subtitle":    "Hands-Free Typing",
        "icon":        "⌨️",
        "description": "Type with your voice and gestures.\nDictation, virtual keyboard, and more.",
        "color":       COLORS["purple"],
        "color_dim":   COLORS["purple_dim"],
        "enabled":     True,
        "script_dir":  "typing_mode",
        "script":      "main.py",
    },
    {
        "id":          "web",
        "title":       "Web Mode",
        "subtitle":    "Hands-Free Browsing",
        "icon":        "🌐",
        "description": "Browse the web with voice commands\nand gesture-based navigation.",
        "color":       COLORS["cyan"],
        "color_dim":   COLORS["cyan_dim"],
        "enabled":     True,
        "script_dir":  "web_mode",
        "script":      "main.py",
    },
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
#  Application
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
#  Application
# ─────────────────────────────────────────────────────────────────────────────
class NavigationLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Desktop Navigation System - Hands-Free Accessibility")
        self.geometry("920x820")
        self.minsize(820, 720)
        self.configure(fg_color=COLORS["bg"])

        # Track running subprocesses: mode_id -> subprocess.Popen
        self._processes: dict[str, subprocess.Popen] = {}
        # Track card widgets for state updates
        self._card_widgets: dict[str, dict] = {}

        # Voice & Assistant
        self.voice_activator = VoiceModeActivator()
        self.assistant = get_assistant()
        self._voice_enabled = False

        # ── Auto Typing Mode — starts when user clicks into any text field ──
        # FocusWatcher polls Windows UIAutomation every 500ms.
        # No voice command needed — typing mode starts/stops automatically.
        self._typing_auto_active = False
        self.focus_watcher = FocusWatcher(
            on_enter=self._auto_start_typing,
            on_leave=self._auto_stop_typing,
        )
        self.focus_watcher.start()

        # ── Whisper bar — shows transcriptions at top of screen ───────────
        self.whisper_bar = WhisperBar(self)
        self.whisper_bar.set_status("⏳ Loading Whisper model…", "#d29922")

        # ── Typing Mode IPC — UDP listener ───────────────────────────────
        # typing_mode/main.py sends JSON events to this port so the
        # WhisperBar can show dictated text without a separate overlay.
        self._typing_udp_port = 19876
        self._start_typing_ipc_listener()

        # ── Web Mode IPC — UDP listener ───────────────────────────────────
        self._web_udp_port = 19877
        self._start_web_ipc_listener()

        # File command handling
        self.ai_handler = None
        self.voice_handler = VoiceHandler()
        self._pending_action = None

        self._build_ui()
        self._setup_voice()
        self._try_init_ai()  # Initialize AI for file commands

        # Auto-enable voice on startup - HANDS-FREE!
        self.after(500, self._auto_enable_voice)

        # Clean up subprocesses on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────────────────────────────────────────────────────────
    #  UI Construction
    # ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────
        header = ctk.CTkFrame(
            self, fg_color=COLORS["surface"], corner_radius=0, height=72)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Title area
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", padx=28, pady=12)

        ctk.CTkLabel(
            title_frame, text="🖥️  Desktop Navigation System",
            font=ctk.CTkFont("Segoe UI Semibold", 22),
            text_color=COLORS["text"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame, text="Hands-free computer control  •  CSE499",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        # Status in header
        self.status_label = ctk.CTkLabel(
            header, text="All systems idle",
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=COLORS["text_dim"],
        )
        self.status_label.pack(side="right", padx=28)

        # ── Separator line ──────────────────────────────────────────────
        sep = ctk.CTkFrame(self, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x")

        # ── Section label ───────────────────────────────────────────────
        section = ctk.CTkFrame(self, fg_color="transparent")
        section.pack(fill="x", padx=32, pady=(24, 4))

        ctk.CTkLabel(
            section, text="Select a Mode",
            font=ctk.CTkFont("Segoe UI Semibold", 15),
            text_color=COLORS["text"],
        ).pack(side="left")

        ctk.CTkLabel(
            section, text="Click a card to start or stop a mode",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=COLORS["text_muted"],
        ).pack(side="right")

        # ── Cards grid ──────────────────────────────────────────────────
        cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        cards_frame.pack(fill="both", expand=True, padx=28, pady=(12, 20))
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)
        cards_frame.rowconfigure(0, weight=1)
        cards_frame.rowconfigure(1, weight=1)

        for i, mode in enumerate(MODE_CARDS):
            row = i // 2
            col = i % 2
            self._create_card(cards_frame, mode, row, col)

        # ── Assistant Panel (LARGER) ──────────────────────────────────
        assistant_panel = ctk.CTkFrame(
            self, fg_color=COLORS["surface2"], corner_radius=8)
        assistant_panel.pack(fill="x", side="bottom", padx=16, pady=(0, 12))
        assistant_panel.columnconfigure(0, weight=1)

        # Header with status indicator
        header_frame = ctk.CTkFrame(assistant_panel, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(12, 0))

        # Status dot and label
        self.status_listening_dot = ctk.CTkLabel(
            header_frame, text="●", font=ctk.CTkFont("Segoe UI", 14),
            text_color=COLORS["green"]
        )
        self.status_listening_dot.pack(side="left")

        self.status_listening_label = ctk.CTkLabel(
            header_frame, text="🎤 Listening...",
            font=ctk.CTkFont("Segoe UI Semibold", 13),
            text_color=COLORS["accent"],
        )
        self.status_listening_label.pack(side="left", padx=8)

        # Keyboard hint (Ctrl+Q)
        ctk.CTkLabel(
            header_frame, text="• Press Ctrl+Q to quit",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=COLORS["text_dim"],
        ).pack(side="right")

        # Assistant message
        self.assistant_text = ctk.CTkLabel(
            assistant_panel, text=self.assistant.get_welcome_message(),
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=COLORS["text"],
            justify="left", wraplength=850,
        )
        self.assistant_text.pack(anchor="nw", padx=16, pady=(8, 12))

        # ── Command Input Section ──────────────────────────────────────
        command_frame = ctk.CTkFrame(assistant_panel, fg_color="transparent")
        command_frame.pack(fill="x", padx=16, pady=(0, 12))
        command_frame.columnconfigure(1, weight=1)

        # Mic button
        self.cmd_mic_btn = ctk.CTkButton(
            command_frame, text="🎙", width=44, height=40,
            fg_color=COLORS["surface"], hover_color=COLORS["border"],
            font=ctk.CTkFont("Segoe UI Emoji", 20),
            corner_radius=8, command=self._start_voice_command
        )
        self.cmd_mic_btn.grid(row=0, column=0, padx=(0, 8))

        # Text input field
        self.cmd_entry = ctk.CTkEntry(
            command_frame, placeholder_text="Type or say: 'open chrome', 'copy files', etc...",
            fg_color=COLORS["surface"], border_color=COLORS["border"],
            text_color=COLORS["text"], font=ctk.CTkFont("Consolas", 12),
            height=40, corner_radius=8
        )
        self.cmd_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self._send_file_command())

        # Send button
        self.cmd_send_btn = ctk.CTkButton(
            command_frame, text="Send", width=80, height=40,
            fg_color=COLORS["accent_glow"], hover_color=COLORS["accent"],
            font=ctk.CTkFont("Segoe UI Semibold", 12),
            corner_radius=8, command=self._send_file_command
        )
        self.cmd_send_btn.grid(row=0, column=2, padx=(0, 0))

        # ── Footer ──────────────────────────────────────────────────────
        footer = ctk.CTkFrame(
            self, fg_color=COLORS["surface"], corner_radius=0, height=40)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkLabel(
            footer, text="🎤 Voice is ALWAYS active • Speak clearly • System is hands-free",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=COLORS["text_dim"],
        ).pack(pady=10)

        # Ctrl+Q to quit
        self.bind("<Control-q>", lambda e: self._on_close())

    def _create_card(self, parent, mode: dict, row: int, col: int):
        """Build a single mode card widget."""
        mode_id = mode["id"]
        is_enabled = mode["enabled"]
        card_color = mode["color_dim"] if is_enabled else COLORS["surface"]
        border_color = mode["color"] if is_enabled else COLORS["border"]

        # Card frame
        card = ctk.CTkFrame(
            parent, fg_color=card_color, corner_radius=14,
            border_width=2, border_color=border_color,
        )
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
        card.columnconfigure(0, weight=1)

        # Icon + Title row
        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=20, pady=(20, 4))

        ctk.CTkLabel(
            top_row, text=mode["icon"],
            font=ctk.CTkFont("Segoe UI Emoji", 32),
        ).pack(side="left")

        title_block = ctk.CTkFrame(top_row, fg_color="transparent")
        title_block.pack(side="left", padx=12)

        ctk.CTkLabel(
            title_block, text=mode["title"],
            font=ctk.CTkFont("Segoe UI Semibold", 17),
            text_color=COLORS["text"] if is_enabled else COLORS["text_dim"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_block, text=mode["subtitle"],
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=mode["color"] if is_enabled else COLORS["text_muted"],
        ).pack(anchor="w")

        # Description
        ctk.CTkLabel(
            card, text=mode["description"],
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=COLORS["text_dim"] if is_enabled else COLORS["text_muted"],
            justify="left",
        ).pack(fill="x", padx=22, pady=(8, 12))

        # Status indicator
        status_frame = ctk.CTkFrame(card, fg_color="transparent")
        status_frame.pack(fill="x", padx=22, pady=(0, 4))

        status_dot = ctk.CTkLabel(
            status_frame, text="●",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=COLORS["text_muted"],
        )
        status_dot.pack(side="left")

        status_text = ctk.CTkLabel(
            status_frame, text="Coming Soon" if not is_enabled else "Idle",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=COLORS["text_muted"],
        )
        status_text.pack(side="left", padx=4)

        # Action button
        if is_enabled:
            btn = ctk.CTkButton(
                card, text="▶  Start",
                font=ctk.CTkFont("Segoe UI Semibold", 14),
                fg_color=mode["color"],
                hover_color=mode["color"],
                text_color="#ffffff",
                corner_radius=10,
                height=42,
                command=lambda m=mode: self._toggle_mode(m),
            )
        else:
            btn = ctk.CTkButton(
                card, text="🔒  Coming Soon",
                font=ctk.CTkFont("Segoe UI", 13),
                fg_color=COLORS["surface2"],
                hover_color=COLORS["surface2"],
                text_color=COLORS["text_muted"],
                corner_radius=10,
                height=42,
                state="disabled",
            )

        btn.pack(fill="x", padx=20, pady=(4, 20))

        # Store widget references for updating state
        self._card_widgets[mode_id] = {
            "card": card,
            "button": btn,
            "status_dot": status_dot,
            "status_text": status_text,
            "mode": mode,
        }

    # ─────────────────────────────────────────────────────────────────────
    #  Voice Control
    # ─────────────────────────────────────────────────────────────────────
    def _setup_voice(self):
        """Setup voice activation system."""
        welcome_msg = self.assistant.get_welcome_message()
        self._update_assistant_message(welcome_msg)

    def _auto_enable_voice(self):
        """Automatically enable voice on startup - HANDS-FREE!"""
        self._enable_voice()
        self._update_listening_status(True)
        # Speak welcome message

    def _enable_voice(self):
        """Enable voice listening."""
        if self._voice_enabled:
            return

        self._voice_enabled = True
        self.voice_activator.start_listening(
            on_mode_activated=self._on_mode_activated,
            on_command=self._on_voice_command,
            on_error=self._on_voice_error,
            on_listening=self._on_listening,
            on_unrecognized=self._on_unrecognized_speech,
            on_mode_stopped=self._on_mode_stopped,
            on_heard=self._on_whisper_heard,
        )

    def _toggle_voice(self):
        """Toggle voice control on/off."""
        if self._voice_enabled:
            self.voice_activator.stop_listening()
            self._voice_enabled = False
            self._update_listening_status(False)
            self._update_assistant_message(
                "Voice listening stopped. System is now available for mouse/keyboard input if needed.")
        else:
            self._enable_voice()
            self._update_listening_status(True)

    def _update_listening_status(self, is_listening: bool):
        """Update the listening status indicator."""
        if is_listening:
            self.status_listening_dot.configure(text_color=COLORS["green"])
            self.status_listening_label.configure(
                text="🎤 Listening...",
                text_color=COLORS["green"]
            )
        else:
            self.status_listening_dot.configure(text_color=COLORS["red"])
            self.status_listening_label.configure(
                text="⏸️ Paused",
                text_color=COLORS["red"]
            )

    def _on_mode_activated(self, mode_id: str):
        """Called when a mode is activated via voice."""
        # Find the mode config
        mode = None
        for card in MODE_CARDS:
            if card["id"] == mode_id:
                mode = card
                break

        if not mode or not mode["enabled"]:
            msg = f"Sorry, {mode_id} mode is not available yet."
            self._update_assistant_message(msg)
            self.assistant.speak_async(msg)
            return

        # Check if already running
        if mode_id in self._processes:
            msg = self.assistant.get_already_running_message(mode_id)
            self._update_assistant_message(msg)
            self.assistant.speak_async(msg)
            return

        # Start the mode
        self._start_mode(mode)
        msg = self.assistant.get_mode_activation_message(mode_id)
        self._update_assistant_message(msg)
        self.assistant.speak_async(msg)

    def _on_voice_command(self, command: str):
        """Called when a voice command is recognized."""
        if command == "help":
            msg = self.assistant.get_help_message()
            self._update_assistant_message(msg)
            self.assistant.speak_async(
                "Here are the available commands. " + msg.split('\n')[0])
        elif command == "stop":
            msg = "Please specify which mode to stop by saying the mode name."
            self._update_assistant_message(msg)
            self.assistant.speak_async(msg)
        else:
            msg = f"Command recognized: {command}"
            self._update_assistant_message(msg)
            self.assistant.speak_async(msg)

    def _on_unrecognized_speech(self, text: str):
        """Called when speech is recognized but doesn't match known commands."""
        # Try to process as a file command if AI handler is available
        if self.ai_handler:
            self._update_assistant_message(f"🎤 Processing: {text}")
            threading.Thread(target=self._process_file_command,
                             args=(text,), daemon=True).start()
        else:
            # Fall back to general Q&A if no AI handler
            response = self.assistant.answer_question(text)
            self._update_assistant_message(response)
            # Speak short version - truncate very long responses
            speak_text = response[:200] if len(response) > 200 else response
            self.assistant.speak_async(speak_text)

    def _on_mode_stopped(self, mode_id: str):
        """Called when user says to stop a mode via voice."""
        if mode_id not in self._processes:
            msg = f"{mode_id.title()} mode is not running."
            self._update_assistant_message(msg)
            self.assistant.speak_async(msg)
            return

        # Stop the mode
        self._stop_mode(mode_id)
        msg = f"{mode_id.title()} mode stopped."
        self._update_assistant_message(msg)
        self.assistant.speak_async(msg)

    def _on_voice_error(self, error_msg: str):
        """Called when voice recognition encounters an error."""
        msg = f"⚠️ Audio issue: {error_msg}"
        self._update_assistant_message(msg)
        self.assistant.speak_async(error_msg)

    def _on_listening(self):
        """Called when the microphone opens — update whisper bar dot."""
        try:
            self.whisper_bar.set_listening(True)
        except Exception:
            pass

    def _on_whisper_heard(self, text: str):
        """Called by VoiceModeActivator with every Whisper transcription."""
        try:
            if text == "__MODEL_READY__":
                # Whisper model finished loading — bar switches to listening state
                self.whisper_bar.set_listening(True)
                self.whisper_bar.set_status("Listening…", "#8b949e")
            else:
                self.whisper_bar.show_heard(text)
        except Exception:
            pass

    def _update_assistant_message(self, message: str):
        """Update the assistant panel message."""
        self.assistant_text.configure(text=message)
        self.update_idletasks()

    # ─────────────────────────────────────────────────────────────────────
    #  Mode Control
    # ─────────────────────────────────────────────────────────────────────
    def _toggle_mode(self, mode: dict):
        """Start or stop a mode."""
        mode_id = mode["id"]

        if mode_id in self._processes:
            self._stop_mode(mode_id)
        else:
            self._start_mode(mode)

    # Modes that own the mic — launcher must yield while these run
    MIC_EXCLUSIVE_MODES = {"web", "typing"}

    def _start_mode(self, mode: dict):
        """Launch the mode's script as a subprocess."""
        mode_id = mode["id"]
        script_dir = os.path.join(BASE_DIR, mode["script_dir"])
        script_path = os.path.join(script_dir, mode["script"])

        if not os.path.exists(script_path):
            self._update_header_status(f"Error: {script_path} not found")
            self._update_assistant_message(f"Error: {script_path} not found")
            return

        try:
            # Build environment that suppresses MediaPipe verbose logging
            env = os.environ.copy()
            # suppress INFO/WARNING from MediaPipe
            env["GLOG_minloglevel"] = "2"
            env["TF_CPP_MIN_LOG_LEVEL"] = "3"   # suppress TensorFlow logs

            # Launch subprocess with NO piping — let it inherit console I/O
            # just like running "python gesture_pilot.py" directly.
            # Piping stdout/stderr breaks OpenCV GUI windows on Windows.
            proc = subprocess.Popen(
                [sys.executable, script_path],
                cwd=script_dir,
                env=env,
            )
            self._processes[mode_id] = proc
            self._set_card_running(mode_id, True)
            self._update_header_status(f"{mode['title']} is running")

            # Mic exclusivity: pause launcher voice and mark flag False
            # so _stop_mode/_poll_process know to resume it later
            if mode_id in self.MIC_EXCLUSIVE_MODES and self._voice_enabled:
                self.voice_activator.stop_listening()
                self._voice_enabled = False          # <-- critical flag update
                self._update_listening_status(False)
                self._update_assistant_message(
                    f"🎙 Mic handed to {mode['title']}. "
                    f"Say \"stop web mode\" inside it to return control."
                )
                if mode_id == "typing":
                    self.after(
                        0, lambda: self.whisper_bar.set_typing_mode(True))
            else:
                if mode_id not in self._processes or self._processes[mode_id] == proc:
                    self._update_assistant_message(
                        self.assistant.get_mode_activation_message(mode_id))

            # Poll for process exit in background
            self.after(1000, lambda: self._poll_process(mode_id))

        except Exception as e:
            self._update_header_status(f"Failed to start {mode['title']}: {e}")
            self._update_assistant_message(
                f"Error: Failed to start {mode['title']}: {e}")

    def _stop_mode(self, mode_id: str):
        """Terminate the subprocess for a mode."""
        proc = self._processes.get(mode_id)
        if proc and proc.poll() is None:
            try:
                # On Windows, terminate() sends TerminateProcess which is reliable
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            except Exception:
                pass

        self._processes.pop(mode_id, None)
        self._set_card_running(mode_id, False)

        # Mic exclusivity: resume launcher voice if no other mic-exclusive
        # mode is still running and we previously yielded (_voice_enabled=False)
        if mode_id in self.MIC_EXCLUSIVE_MODES:
            still_exclusive = any(
                m in self.MIC_EXCLUSIVE_MODES for m in self._processes)
            if not still_exclusive and not self._voice_enabled:
                self._enable_voice()                 # sets _voice_enabled=True internally
                self._update_listening_status(True)
            if mode_id == "typing":
                self.after(0, lambda: self.whisper_bar.set_typing_mode(False))
            if mode_id == "web":
                self.after(0, lambda: self.whisper_bar.set_web_mode(False))

        # Update header and assistant
        running = [self._card_widgets[m]["mode"]["title"]
                   for m in self._processes if m in self._card_widgets]
        if running:
            self._update_header_status(f"Running: {', '.join(running)}")
            self._update_assistant_message(
                f"Mode stopped. Currently running: {', '.join(running)}")
        else:
            self._update_header_status("All systems idle")
            self._update_assistant_message(
                "All systems idle. Say a mode name to activate it.")

    # ── Typing Mode IPC ──────────────────────────────────────────────────────

    def _start_typing_ipc_listener(self):
        """
        Listen on a UDP socket for events from the typing_mode subprocess.
        Events are JSON: {"event": "typed"|"status"|"command", "data": "..."}
        Runs in a daemon thread — won't block launcher shutdown.
        """
        import threading
        import socket
        import json as _json

        def _listen():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", self._typing_udp_port))
                sock.settimeout(1.0)
                while True:
                    try:
                        data, _ = sock.recvfrom(4096)
                        msg = _json.loads(data.decode("utf-8"))
                        event = msg.get("event")
                        payload = msg.get("data", "")
                        if event == "typed":
                            self.after(0, self.whisper_bar.show_typed, payload)
                        elif event == "status":
                            # e.g. "Listening", "Paused", "Stopped"
                            if "stop" in payload.lower() or "stopped" in payload.lower():
                                self.after(
                                    0, self.whisper_bar.set_typing_mode, False)
                            elif "listen" in payload.lower() or "ready" in payload.lower():
                                self.after(
                                    0, self.whisper_bar.set_typing_mode, True)
                        elif event == "command":
                            # Show voice commands (new line, delete that, etc.)
                            self.after(
                                0, self.whisper_bar.show_heard, f"⚡ {payload}")
                    except socket.timeout:
                        continue
                    except Exception:
                        continue
            except Exception as e:
                print(f"[Launcher] Typing IPC listener error: {e}")
        threading.Thread(target=_listen, daemon=True,
                         name="typing-ipc").start()

    def _start_web_ipc_listener(self):
        """
        Listen on UDP 19877 for events from the web_mode subprocess.
        Events: status, heard, typed, page, connected, web_started, web_stopped, web_typing
        """
        import threading
        import socket
        import json as _json

        def _listen():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", self._web_udp_port))
                sock.settimeout(1.0)
                while True:
                    try:
                        data, _ = sock.recvfrom(4096)
                        msg = _json.loads(data.decode("utf-8"))
                        event = msg.get("event")
                        payload = msg.get("data", "")
                        if event == "web_started":
                            self.after(
                                0, lambda: self.whisper_bar.set_web_mode(True))
                        elif event == "web_stopped":
                            self.after(
                                0, lambda: self.whisper_bar.set_web_mode(False))
                        elif event == "web_typing":
                            # Input field clicked in browser — show typing indicator
                            self.after(0, lambda p=payload: self.whisper_bar.show_web_event(
                                f"⌨ Typing: {p}"))
                        elif event == "typed":
                            self.after(
                                0, lambda p=payload: self.whisper_bar.show_web_event(f"⌨ {p}"))
                        elif event in ("heard", "status", "page", "connected"):
                            self.after(
                                0, lambda p=payload: self.whisper_bar.show_web_event(p))
                        elif event == "error":
                            self.after(
                                0, lambda p=payload: self.whisper_bar.show_web_event(f"⚠ {p}"))
                    except socket.timeout:
                        continue
                    except Exception:
                        continue
            except Exception as e:
                print(f"[Launcher] Web IPC listener error: {e}")
        threading.Thread(target=_listen, daemon=True, name="web-ipc").start()

    # ── Auto Typing Mode callbacks (called by FocusWatcher) ─────────────────

    def _auto_start_typing(self):
        """
        Called by FocusWatcher when the user clicks into a text field.
        Starts typing mode silently — no voice command required.

        Guards:
          - Does nothing if typing mode is already running (manual or auto)
          - Does nothing if a mic-exclusive mode is already using the mic
        """
        # Already running — nothing to do
        if "typing" in self._processes:
            return

        # Some other mic-exclusive mode is active (e.g. web mode) — don't interfere
        still_exclusive = any(m in self.MIC_EXCLUSIVE_MODES
                              for m in self._processes if m != "typing")
        if still_exclusive:
            return

        # Find the typing mode config dict from MODES list
        typing_mode = next(
            (m for m in MODE_CARDS if m["id"] == "typing"), None)
        if typing_mode is None:
            return

        print("[Launcher] FocusWatcher: text field focused → auto-starting Typing Mode")
        self._typing_auto_active = True
        self.after(0, lambda: self._start_mode(typing_mode))
        self.after(0, lambda: self._update_assistant_message(
            "⌨ Text field detected — Typing Mode activated automatically. "
            "Speak to type. Click outside to stop."
        ))
        self.after(0, lambda: self.whisper_bar.set_typing_mode(True))

    def _auto_stop_typing(self):
        """
        Called by FocusWatcher when focus leaves a text field.
        Stops typing mode only if WE auto-started it (not if user started it manually).
        """
        if not self._typing_auto_active:
            return   # user started it manually — don't auto-stop

        if "typing" not in self._processes:
            self._typing_auto_active = False
            return

        print(
            "[Launcher] FocusWatcher: focus left text field → auto-stopping Typing Mode")
        self._typing_auto_active = False
        self.after(0, lambda: self._stop_mode("typing"))
        self.after(0, lambda: self._update_assistant_message(
            "⌨ Text field lost — Typing Mode stopped."
        ))

    def _poll_process(self, mode_id: str):
        """Check if a subprocess has exited on its own."""
        proc = self._processes.get(mode_id)
        if proc is None:
            return

        if proc.poll() is not None:
            # Process has exited — check for crash
            exit_code = proc.returncode
            self._processes.pop(mode_id, None)
            self._set_card_running(mode_id, False)

            # Mic exclusivity: resume if mic-exclusive mode exited on its own
            # (e.g. user said "stop web mode" / "turn off web mode" inside it)
            if mode_id in self.MIC_EXCLUSIVE_MODES:
                still_exclusive = any(
                    m in self.MIC_EXCLUSIVE_MODES for m in self._processes)
                if not still_exclusive and not self._voice_enabled:
                    self._enable_voice()             # sets _voice_enabled=True internally
                    self._update_listening_status(True)
                    self._update_assistant_message(
                        "🎙 Mic returned to launcher. Say a mode name to continue."
                    )

            title = self._card_widgets[mode_id]["mode"]["title"]
            if exit_code != 0:
                self._update_header_status(
                    f"{title} exited with error (code {exit_code})")
            else:
                running = [self._card_widgets[m]["mode"]["title"]
                           for m in self._processes if m in self._card_widgets]
                if running:
                    self._update_header_status(
                        f"Running: {', '.join(running)}")
                else:
                    self._update_header_status("All systems idle")
        else:
            # Still running, check again
            self.after(1000, lambda: self._poll_process(mode_id))

    # ─────────────────────────────────────────────────────────────────────
    #  File Command Handling (Action Mode Integrated)
    # ─────────────────────────────────────────────────────────────────────
    def _try_init_ai(self):
        """Initialize AIHandler if API key exists."""
        env_path = os.path.join(os.path.dirname(
            __file__), 'file_commander', '.env')
        try:
            self.ai_handler = AIHandler() if os.path.exists(env_path) else None
        except:
            self.ai_handler = None

    def _start_voice_command(self):
        """Start listening for a voice file command."""
        if not hasattr(self, 'voice_handler'):
            self.voice_handler = VoiceHandler()

        if self.voice_handler.is_listening:
            return

        self.cmd_mic_btn.configure(fg_color=COLORS["red"])
        self._update_assistant_message("🎙 Listening for command...")

        self.voice_handler.listen_once(
            on_result=self._on_file_voice_result,
            on_error=self._on_file_voice_error,
            on_listening=lambda: None
        )

    def _on_file_voice_result(self, text: str):
        """Handle voice recognition result for file commands."""
        self.cmd_mic_btn.configure(fg_color=COLORS["surface"])
        self.cmd_entry.delete(0, "end")
        self.cmd_entry.insert(0, text)
        self._update_assistant_message(
            f"🎤 Recognized: \"{text}\"\nProcessing...")
        self.after(300, self._send_file_command, text)

    def _on_file_voice_error(self, msg: str):
        """Handle voice recognition errors."""
        self.cmd_mic_btn.configure(fg_color=COLORS["surface"])
        self._update_assistant_message(f"❌ Voice error: {msg}")
        self.assistant.speak_async(f"Voice error: {msg}")

    def _send_file_command(self, text: str = ""):
        """Send a file command to AI processor."""
        if not self.ai_handler:
            msg = "⚠️  Groq API not configured. Add GROQ_API_KEY to file_commander/.env\nExample: GROQ_API_KEY=gsk_..."
            self._update_assistant_message(msg)
            self.assistant.speak_async(
                "API key not configured. Please set up your Groq API key.")
            return

        cmd = text or self.cmd_entry.get().strip()
        if not cmd:
            return

        self.cmd_entry.delete(0, "end")
        self.cmd_send_btn.configure(state="disabled")
        self._update_assistant_message(f"⚙️  Processing: {cmd}")

        threading.Thread(target=self._process_file_command,
                         args=(cmd,), daemon=True).start()

    def _process_file_command(self, cmd: str):
        """Process file command through AI handler."""
        try:
            action = self.ai_handler.parse_command(cmd)
            desc = action.get("description", "")

            self.after(0, self._update_assistant_message, f"🤖 AI: {desc}")

            if action.get("requires_confirmation"):
                self._pending_action = action
                self.after(0, self._ask_file_confirmation, desc)
            else:
                self.after(0, self._run_file_action, action)
        except Exception as e:
            self.after(0, self._update_assistant_message, f"❌ Error: {str(e)}")
            self.after(0, self.cmd_send_btn.configure, {"state": "normal"})

    def _ask_file_confirmation(self, desc: str):
        """Ask user to confirm destructive operation."""
        self._update_assistant_message(f"⚠️  Destructive operation — confirm?")
        answer = messagebox.askyesno(
            "Confirm Action",
            f"Are you sure?\n\n{desc}\n\nThis cannot be undone."
        )
        if answer and hasattr(self, '_pending_action'):
            self._run_file_action(self._pending_action)
        else:
            self._update_assistant_message("🚫 Operation cancelled.")
        self.cmd_send_btn.configure(state="normal")

    def _run_file_action(self, action: dict):
        """Execute the file action."""
        threading.Thread(target=self._execute_file_action,
                         args=(action,), daemon=True).start()

    def _execute_file_action(self, action: dict):
        """Execute file operation in background thread."""
        ok, msg = execute_action(action)
        status_text = "✅ Done" if ok else f"❌ {msg}"
        self.after(0, self._update_assistant_message, status_text)
        self.after(0, self.cmd_send_btn.configure, {"state": "normal"})

        # Speak result
        if ok:
            self.assistant.speak_async("Operation completed successfully")
        else:
            self.assistant.speak_async(f"Operation failed: {msg}")

    # ─────────────────────────────────────────────────────────────────────
    #  UI State Updates
    # ─────────────────────────────────────────────────────────────────────
    def _set_card_running(self, mode_id: str, is_running: bool):
        """Update card visuals for running/stopped state."""
        widgets = self._card_widgets.get(mode_id)
        if not widgets:
            return

        mode = widgets["mode"]
        btn = widgets["button"]
        dot = widgets["status_dot"]
        txt = widgets["status_text"]
        card = widgets["card"]

        if is_running:
            btn.configure(
                text="■  Stop",
                fg_color=COLORS["red"],
                hover_color=COLORS["red"],
            )
            dot.configure(text_color=COLORS["green"])
            txt.configure(text="Running", text_color=COLORS["green"])
            card.configure(border_color=COLORS["green"])
        else:
            btn.configure(
                text="▶  Start",
                fg_color=mode["color"],
                hover_color=mode["color"],
            )
            dot.configure(text_color=COLORS["text_muted"])
            txt.configure(text="Idle", text_color=COLORS["text_muted"])
            card.configure(border_color=mode["color"])

    def _update_header_status(self, text: str):
        """Update the status label in the header."""
        self.status_label.configure(text=text)

    # ─────────────────────────────────────────────────────────────────────
    #  Cleanup
    # ─────────────────────────────────────────────────────────────────────
    def _on_close(self):
        """Terminate all subprocesses and close the app."""
        for mode_id in list(self._processes.keys()):
            self._stop_mode(mode_id)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = NavigationLauncher()
    app.mainloop()
