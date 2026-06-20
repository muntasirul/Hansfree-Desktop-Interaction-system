"""
typing_engine.py — Core logic for Typing Mode.

Speech-to-text engine: faster-whisper (small.en)
─────────────────────────────────────────────────
WHY faster-whisper instead of Google Speech API:
  • 100% offline — no internet, no API key, no request limits
  • Much higher accuracy for dictation (handles accents, technical words)
  • small.en model = English-only, 244 MB, fast on CPU
  • Built-in VAD (Silero) removes silence before transcription automatically
  • int8 quantization = ~3–4× faster than fp32 with negligible quality loss

HOW IT WORKS (3 threads):
  Thread 1 — _mic_loop:        PyAudio captures raw PCM from mic
                                RMS energy VAD detects speech vs silence
                                Completed speech segments → _audio_queue
  Thread 2 — _recognizer_loop: Pulls audio from _audio_queue
                                Runs faster-whisper transcription
                                Pushes text result → _text_queue
  Thread 3 — _typer_loop:      Pulls text from _text_queue
                                Parses commands vs plain text
                                Types into whatever window is focused

INSTALL:
  pip install faster-whisper pyaudio pyautogui pyperclip numpy

Model auto-downloads to ~/.cache/huggingface/hub/ on first run (~244 MB).
Every run after that loads from cache instantly (< 1 second).
"""

import threading
import queue
import time
import math
import numpy as np
import pyautogui

# ── Optional clipboard typing (handles unicode / emoji) ───────────────────────
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

# ── faster-whisper ────────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[TypingEngine] MISSING: faster-whisper")
    print("               Fix:  pip install faster-whisper")

# ── PyAudio (mic capture) ─────────────────────────────────────────────────────
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("[TypingEngine] MISSING: pyaudio")
    print("               Fix:  pip install pyaudio")


# ─────────────────────────────────────────────────────────────────────────────
#  Whisper config  (edit these to tune behaviour)
# ─────────────────────────────────────────────────────────────────────────────

WHISPER_MODEL = "small.en"  # 244 MB — best accuracy/speed for English CPU
# Other options: "tiny.en" (fast), "medium.en" (slow but accurate)
WHISPER_DEVICE = "cpu"        # "cuda" if you have an NVIDIA GPU
WHISPER_COMPUTE = "int8"       # "int8" = fastest on CPU, tiny accuracy loss
# "float16" for GPU, "float32" for max accuracy

# ─────────────────────────────────────────────────────────────────────────────
#  Audio capture config
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000   # Hz — Whisper requires exactly 16 kHz
CHANNELS = 1       # mono
CHUNK_FRAMES = 1024    # PyAudio frames per read call

# Voice Activity Detection (VAD) — silence detection
# RMS energy below this = silence (raise if false triggers)
SILENCE_RMS = 500
SILENCE_SECS = 1.2     # seconds of silence that ends a speech segment
MIN_SPEECH_SECS = 0.4     # clips shorter than this are ignored (noise bursts)
MAX_SPEECH_SECS = 15.0    # safety cap — forces flush after this duration

# Whisper hallucination filter — these phrases appear when Whisper hears silence
HALLUCINATIONS = {
    "", ".", "...", "…",
    "thank you.", "thanks for watching.", "thanks.", "you",
    "bye.", "bye bye.", "see you next time.",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Voice command mappings
# ─────────────────────────────────────────────────────────────────────────────

CONTROL_COMMANDS = {
    # Punctuation
    "period":            ".",
    "full stop":         ".",
    "dot":               ".",
    "comma":             ",",
    "exclamation mark":  "!",
    "exclamation":       "!",
    "question mark":     "?",
    "colon":             ":",
    "semicolon":         ";",
    "apostrophe":        "'",
    "open bracket":      "(",
    "close bracket":     ")",
    "open parenthesis":  "(",
    "close parenthesis": ")",
    "hyphen":            "-",
    "dash":              "-",
    "underscore":        "_",
    "at sign":           "@",
    "hash":              "#",
    "percent":           "%",
    "ampersand":         "&",
    "asterisk":          "*",
    "equals":            "=",
    "plus":              "+",
    "slash":             "/",
    "quote":             '"',
    "open quote":        '"',
    "close quote":       '"',

    # Whitespace / formatting
    "new line":          "\n",
    "newline":           "\n",
    "enter":             "\n",
    "tab":               "\t",
    "space":             " ",

    # Capitalization
    "caps lock":         "__CAPS__",
    "all caps":          "__CAPS__",

    # Editing actions
    "delete that":       "__DELETE_WORD__",
    "delete word":       "__DELETE_WORD__",
    "backspace":         "__BACKSPACE__",
    "undo":              "__UNDO__",
    "redo":              "__REDO__",
    "select all":        "__SELECT_ALL__",
    "copy that":         "__COPY__",
    "copy":              "__COPY__",
    "paste":             "__PASTE__",
    "cut that":          "__CUT__",
    "cut":               "__CUT__",

    # Navigation
    "go home":           "__HOME__",
    "go end":            "__END__",
    "go to end":         "__END__",
    "go to start":       "__HOME__",
    "next line":         "__DOWN__",
    "previous line":     "__UP__",
    "move right":        "__RIGHT__",
    "move left":         "__LEFT__",

    # Session control
    "stop typing":       "__STOP__",
    "pause typing":      "__PAUSE__",
    "resume typing":     "__RESUME__",
    "clear all":         "__CLEAR__",

    # Correction
    "scratch that":      "__SCRATCH__",
    "delete last":       "__SCRATCH__",
}

# Filler words Whisper sometimes includes — strip these from dictation
FILLER_WORDS = {"um", "uh", "er", "ah"}


# ─────────────────────────────────────────────────────────────────────────────
#  TypingEngine
# ─────────────────────────────────────────────────────────────────────────────

class TypingEngine:
    """
    Continuously listens with faster-whisper and types into the active window.

    Lifecycle:
        engine = TypingEngine(on_status=..., on_text=..., on_command=..., on_error=...)
        engine.run()      # blocks until stop() is called — call from a thread
        engine.stop()     # signals all loops to exit cleanly
    """

    def __init__(
        self,
        on_status=None,   # callback(str) — status text shown in overlay
        on_text=None,     # callback(str) — text that was just typed
        on_command=None,  # callback(str) — voice command that was executed
        on_error=None,    # callback(str) — error message
    ):
        self.on_status = on_status or (lambda s: print(f"[Status] {s}"))
        self.on_text = on_text or (lambda t: print(f"[Typed]  {t}"))
        self.on_command = on_command or (lambda c: print(f"[Cmd]    {c}"))
        self.on_error = on_error or (lambda e: print(f"[Error]  {e}"))

        self.is_running = False
        self.is_paused = False
        self._stop_event = threading.Event()

        # ── Whisper model (loaded once in run()) ──────────────────────────
        self._model: WhisperModel = None

        # ── Thread communication queues ───────────────────────────────────
        # mic_loop → recognizer_loop: numpy float32 arrays (one per utterance)
        self._audio_queue: queue.Queue = queue.Queue()
        # recognizer_loop → typer_loop: transcribed text strings
        self._text_queue:  queue.Queue = queue.Queue()

        # ── State ─────────────────────────────────────────────────────────
        self._last_typed = ""    # used by "scratch that"
        self._caps_lock = False

    # ─────────────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        """Load Whisper, start all threads, block until stop() is called."""
        self.is_running = True
        self._stop_event.clear()

        # Step 1: Load the Whisper model (blocks here — shows status in overlay)
        self.on_status("⏳ Loading Whisper model…")
        if not self._load_model():
            self.is_running = False
            return   # error already reported via on_error

        # Step 2: Start the three worker threads
        threading.Thread(target=self._mic_loop,
                         daemon=True, name="mic").start()
        threading.Thread(target=self._recognizer_loop,
                         daemon=True, name="recog").start()
        threading.Thread(target=self._typer_loop,
                         daemon=True, name="typer").start()

        self.on_status("🎙 Listening — speak to type")

        # Block the caller's thread until stop() sets the event
        self._stop_event.wait()

        self.is_running = False
        self.on_status("⏹ Typing Mode stopped")

    def stop(self):
        self._stop_event.set()
        self.is_running = False

    def pause(self):
        self.is_paused = True
        self.on_status("⏸ Paused — say 'resume typing' to continue")

    def resume(self):
        self.is_paused = False
        self.on_status("🎙 Listening — speak to type")

    # ─────────────────────────────────────────────────────────────────────────
    #  Thread 0 — Model loading
    # ─────────────────────────────────────────────────────────────────────────

    def _load_model(self) -> bool:
        """
        Load the Whisper model. Returns True on success.

        First run: downloads ~244 MB to ~/.cache/huggingface/hub/
        Subsequent runs: loads from cache in < 1 second.
        """
        if not WHISPER_AVAILABLE:
            self.on_error(
                "faster-whisper not installed — run: pip install faster-whisper")
            return False
        try:
            print(
                f"[TypingEngine] Loading faster-whisper {WHISPER_MODEL} on {WHISPER_DEVICE}…")
            self._model = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE,
            )
            print("[TypingEngine] ✓ Model ready")
            self.on_status("✓ Whisper ready")
            return True
        except Exception as e:
            self.on_error(f"Model load failed: {e}")
            print(f"[TypingEngine] Model load error: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Thread 1 — Mic capture with RMS VAD
    # ─────────────────────────────────────────────────────────────────────────

    def _mic_loop(self):
        """
        Open the microphone with PyAudio and stream audio chunks.

        Voice Activity Detection (VAD) logic:
          - Read CHUNK_FRAMES of int16 PCM each iteration
          - Compute RMS energy of each chunk
          - If RMS > SILENCE_RMS  →  speech is happening, accumulate chunks
          - If RMS ≤ SILENCE_RMS  →  silence; after SILENCE_SECS, flush buffer
          - Flushed buffer is converted to float32 [-1,1] and put on _audio_queue
        """
        if not PYAUDIO_AVAILABLE:
            self.on_error("pyaudio not installed — run: pip install pyaudio")
            return

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_FRAMES,
            )
            print("[TypingEngine] ✓ Mic open")

            buf = []          # accumulates int16 chunks for current utterance
            silence_t = None        # timestamp when silence began
            in_speech = False       # currently inside a speech segment

            while not self._stop_event.is_set():
                if self.is_paused:
                    time.sleep(0.1)
                    continue

                # Read one chunk of raw PCM
                try:
                    raw = stream.read(
                        CHUNK_FRAMES, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.05)
                    continue

                chunk = np.frombuffer(raw, dtype=np.int16)
                rms = math.sqrt(max(1, np.mean(chunk.astype(np.float32) ** 2)))

                if rms > SILENCE_RMS:
                    # ── Speech detected ───────────────────────────────────
                    in_speech = True
                    silence_t = None
                    buf.append(chunk)

                    # Safety flush — never hold more than MAX_SPEECH_SECS
                    if len(buf) * CHUNK_FRAMES / SAMPLE_RATE >= MAX_SPEECH_SECS:
                        self._flush(buf)
                        buf = []
                        in_speech = False

                else:
                    # ── Silence ───────────────────────────────────────────
                    if in_speech:
                        # include trailing silence
                        buf.append(chunk)

                        if silence_t is None:
                            silence_t = time.time()
                        elif time.time() - silence_t >= SILENCE_SECS:
                            # Long enough pause — speech segment is complete
                            self._flush(buf)
                            buf = []
                            silence_t = None
                            in_speech = False

        except Exception as e:
            if not self._stop_event.is_set():
                self.on_error(f"Mic error: {e}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            pa.terminate()
            print("[TypingEngine] Mic closed")

    def _flush(self, buf: list):
        """
        Convert accumulated int16 chunks to float32 and send to recognizer.
        Whisper expects float32 in range [-1.0, 1.0] at 16 kHz.
        """
        if not buf:
            return
        duration = len(buf) * CHUNK_FRAMES / SAMPLE_RATE
        if duration < MIN_SPEECH_SECS:
            return   # too short — noise burst, ignore

        audio = np.concatenate(buf).astype(np.float32) / 32768.0
        self._audio_queue.put(audio)

    # ─────────────────────────────────────────────────────────────────────────
    #  Thread 2 — Whisper transcription
    # ─────────────────────────────────────────────────────────────────────────

    def _recognizer_loop(self):
        """
        Pull audio clips from _audio_queue and transcribe with faster-whisper.

        Key Whisper parameters used:
          beam_size=5            — wider beam = higher accuracy (vs speed)
          vad_filter=True        — Silero VAD removes silence before transcription
          no_speech_threshold    — clips below this confidence are silently skipped
          temperature=0.0        — greedy decoding = deterministic, fewer hallucinations
          condition_on_previous  — False: each clip is independent (no bleed-over)
        """
        while not self._stop_event.is_set():
            try:
                audio = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._model is None:
                continue

            try:
                self.on_status("⚙ Transcribing…")

                segments, _ = self._model.transcribe(
                    audio,
                    language="en",
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                    no_speech_threshold=0.6,
                    condition_on_previous_text=False,
                    temperature=0.0,
                )

                # Collect segment text, filter hallucinations
                parts = []
                for seg in segments:
                    t = seg.text.strip()
                    if t.lower() not in HALLUCINATIONS:
                        parts.append(t)

                text = " ".join(parts).strip()
                if text:
                    print(f"[TypingEngine] '{text}'")
                    self._text_queue.put(text)

                self.on_status("🎙 Listening — speak to type")

            except Exception as e:
                if not self._stop_event.is_set():
                    self.on_error(f"Transcription error: {e}")
                    self.on_status("🎙 Listening — speak to type")

    # ─────────────────────────────────────────────────────────────────────────
    #  Thread 3 — Command parsing + typing
    #  (unchanged from original — all logic below is identical)
    # ─────────────────────────────────────────────────────────────────────────

    def _typer_loop(self):
        """Pull from queue and type into active window."""
        while not self._stop_event.is_set():
            try:
                text = self._text_queue.get(timeout=0.5)
                self._process_and_type(text)
            except queue.Empty:
                continue

    def _process_and_type(self, raw_text: str):
        """Parse text for commands and type remainder."""
        if not raw_text:
            return

        text_lower = raw_text.lower().strip()

        # ── Full control command ──
        if text_lower in CONTROL_COMMANDS:
            self._execute_command(text_lower, CONTROL_COMMANDS[text_lower])
            return

        # ── Command at START of phrase ──
        for cmd, value in CONTROL_COMMANDS.items():
            if text_lower.startswith(cmd + " "):
                self._execute_command(cmd, value)
                remainder = raw_text[len(cmd):].strip()
                if remainder:
                    self._type_text(remainder)
                return

        # ── Command at END of phrase ──
        for cmd, value in CONTROL_COMMANDS.items():
            if text_lower.endswith(" " + cmd):
                body = raw_text[:-(len(cmd) + 1)].strip()
                if body:
                    self._type_text(body)
                self._execute_command(cmd, value)
                return

        # ── Plain text — clean filler words and type ──
        cleaned = self._clean_text(raw_text)
        if cleaned:
            self._type_text(cleaned)

    def _clean_text(self, text: str) -> str:
        """Remove filler words and apply caps lock if active."""
        words = text.split()
        cleaned = [w for w in words if w.lower() not in FILLER_WORDS]
        result = " ".join(cleaned)
        if self._caps_lock:
            result = result.upper()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    #  Typing
    # ─────────────────────────────────────────────────────────────────────────

    def _type_text(self, text: str):
        """Type text into the currently focused application."""
        if not text:
            return

        # Add trailing space unless text ends with punctuation
        text_to_type = text if text[-1] in ".,!?;:)]} " else text + " "
        self._last_typed = text_to_type

        try:
            if CLIPBOARD_AVAILABLE:
                # Clipboard paste — handles unicode, accented chars, emoji
                original = pyperclip.paste()
                pyperclip.copy(text_to_type)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.05)
                pyperclip.copy(original)
            else:
                # Fallback: direct keystroke simulation (ASCII only)
                pyautogui.typewrite(text_to_type, interval=0.02)

            self.on_text(text_to_type)
            preview = text_to_type[:40] + \
                ("…" if len(text_to_type) > 40 else "")
            self.on_status(f"✅ Typed: {preview}")

        except Exception as e:
            self.on_error(f"Typing error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Command execution
    # ─────────────────────────────────────────────────────────────────────────

    def _execute_command(self, cmd_phrase: str, value: str):
        """Execute a control command."""
        self.on_command(cmd_phrase)

        # Single printable character (punctuation)
        if len(value) == 1:
            self._type_text(value)
            return

        if value == "\n":
            pyautogui.press("enter")
            self.on_status("↩ New line")

        elif value == "\t":
            pyautogui.press("tab")
            self.on_status("⇥ Tab")

        elif value == "__DELETE_WORD__":
            pyautogui.hotkey("ctrl", "backspace")
            self.on_status("🗑 Deleted word")

        elif value == "__BACKSPACE__":
            pyautogui.press("backspace")
            self.on_status("⌫ Backspace")

        elif value == "__UNDO__":
            pyautogui.hotkey("ctrl", "z")
            self.on_status("↩ Undo")

        elif value == "__REDO__":
            pyautogui.hotkey("ctrl", "y")
            self.on_status("↪ Redo")

        elif value == "__SELECT_ALL__":
            pyautogui.hotkey("ctrl", "a")
            self.on_status("☑ Select all")

        elif value == "__COPY__":
            pyautogui.hotkey("ctrl", "c")
            self.on_status("📋 Copied")

        elif value == "__PASTE__":
            pyautogui.hotkey("ctrl", "v")
            self.on_status("📋 Pasted")

        elif value == "__CUT__":
            pyautogui.hotkey("ctrl", "x")
            self.on_status("✂ Cut")

        elif value == "__HOME__":
            pyautogui.hotkey("ctrl", "home")
            self.on_status("⬆ Go to start")

        elif value == "__END__":
            pyautogui.hotkey("ctrl", "end")
            self.on_status("⬇ Go to end")

        elif value == "__UP__":
            pyautogui.press("up")

        elif value == "__DOWN__":
            pyautogui.press("down")

        elif value == "__LEFT__":
            pyautogui.press("left")

        elif value == "__RIGHT__":
            pyautogui.press("right")

        elif value == "__CAPS__":
            self._caps_lock = not self._caps_lock
            self.on_status(f"🔠 Caps Lock {'ON' if self._caps_lock else 'OFF'}")

        elif value == "__STOP__":
            self.on_status("⏹ Stopping…")
            self.stop()

        elif value == "__PAUSE__":
            self.pause()

        elif value == "__RESUME__":
            self.resume()

        elif value == "__SCRATCH__":
            if self._last_typed:
                for _ in range(len(self._last_typed)):
                    pyautogui.press("backspace")
                self.on_status(f"🗑 Scratched: '{self._last_typed.strip()}'")
                self._last_typed = ""

        elif value == "__CLEAR__":
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("delete")
            self.on_status("🗑 Cleared all text")
