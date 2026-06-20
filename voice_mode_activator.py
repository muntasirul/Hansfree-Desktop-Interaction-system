"""
voice_mode_activator.py — Voice commands to activate/deactivate modes.

Speech engine: faster-whisper tiny.en
  • Runs 100% offline — no internet, no API key
  • tiny.en = ~75 MB, loads in < 1 second after first download
  • Fast enough for short keyword clips (mode names are 1–3 words)
  • Shared model instance — loaded once, reused every listen cycle

Install:
    pip install faster-whisper pyaudio numpy
"""

import threading
import time
import math
import numpy as np
from typing import Callable, Optional

# ── faster-whisper ────────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[VoiceActivator] MISSING: faster-whisper — run: pip install faster-whisper")

# ── PyAudio ───────────────────────────────────────────────────────────────────
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("[VoiceActivator] MISSING: pyaudio — run: pip install pyaudio")


# ─────────────────────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────────────────────

WHISPER_MODEL = "tiny.en"   # 75 MB — ~0.1-0.3s transcription, fast enough for keywords
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_FRAMES = 1024

# RMS below this = silence (lower = more sensitive mic start)
SILENCE_RMS = 350
SILENCE_SECS = 0.6         # silence duration that ends a speech segment
MIN_SPEECH_SECS = 0.3         # minimum clip length (ignore noise bursts)
MAX_SPEECH_SECS = 6.0         # maximum utterance length

HALLUCINATIONS = {
    "", ".", "...", "…",
    "thank you.", "thanks.", "thanks for watching.",
    "bye.", "you", "see you next time.",
}


class VoiceModeActivator:
    """
    Listens for voice commands and activates/deactivates modes.
    Uses faster-whisper tiny.en — fully offline.
    """

    MODE_KEYWORDS = {
        "cursor": ["cursor mode", "cursor", "navigation mode", "nose tracking", "activate cursor"],
        "action": ["action mode", "action", "file mode", "command mode", "activate action"],
        "typing": ["typing mode", "typing", "hands free typing", "voice typing",
                   "activate typing", "start typing", "open typing mode"],
        "web":    ["web mode", "web", "browser mode", "web browsing",
                   "activate web", "start web", "open web mode", "launch web"],
    }

    STOP_MODE_KEYWORDS = {
        "cursor": ["stop cursor", "stop cursor mode", "close cursor", "disable cursor", "end cursor"],
        "action": ["stop action", "stop action mode", "close action", "disable action", "end action"],
        "typing": ["stop typing", "stop typing mode", "close typing", "disable typing",
                   "end typing", "close typing mode", "exit typing"],
        "web":    ["stop web", "stop web mode", "close web", "disable web", "end web",
                   "close web mode", "exit web", "exit web mode", "kill web"],
    }

    OTHER_COMMANDS = {
        "help": ["help", "what can i do", "tell me about modes", "assistance"],
        # NOTE: bare "stop" removed — it matched mid-sentence words like
        # "stop, first they're moving". Use specific stop phrases instead:
        # "stop all", "stop everything", "quit all"
        "stop": ["stop all", "stop everything", "quit all"],
    }

    def __init__(self):
        self._is_listening = False
        self._is_enabled = False
        self._on_unrecognized_callback = None
        self._on_mode_stopped_callback = None
        self._on_heard_callback = None

        # Shared Whisper model — loaded once in background
        self._model = None
        self._model_lock = threading.Lock()
        self._model_ready = False

        threading.Thread(target=self._load_model, daemon=True,
                         name="vma-model-load").start()

    # ── Model ─────────────────────────────────────────────────────────────────

    def _load_model(self):
        if not WHISPER_AVAILABLE:
            return
        try:
            print(
                f"[VoiceActivator] Loading faster-whisper {WHISPER_MODEL}...")
            m = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE,
                             compute_type=WHISPER_COMPUTE)
            with self._model_lock:
                self._model = m
                self._model_ready = True
            print("[VoiceActivator] Model ready")
            # If launcher registered an on_heard callback, use it to signal
            # bar to switch from "loading" to "listening" state
            if self._on_heard_callback:
                try:
                    self._on_heard_callback("__MODEL_READY__")
                except Exception:
                    pass
        except Exception as e:
            print(f"[VoiceActivator] Model load error: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def start_listening(self, on_mode_activated, on_command, on_error,
                        on_listening, on_unrecognized=None, on_mode_stopped=None,
                        on_heard=None):
        self._is_enabled = True
        self._on_unrecognized_callback = on_unrecognized
        self._on_mode_stopped_callback = on_mode_stopped
        self._on_heard_callback = on_heard
        threading.Thread(
            target=self._loop,
            args=(on_mode_activated, on_command, on_error, on_listening),
            daemon=True, name="vma-loop"
        ).start()

    def stop_listening(self):
        self._is_enabled = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self, on_mode_activated, on_command, on_error, on_listening):
        while self._is_enabled:
            self._listen_once(on_mode_activated, on_command,
                              on_error, on_listening)

    def _listen_once(self, on_mode_activated, on_command, on_error, on_listening):
        """Capture one speech segment and transcribe it."""
        if not PYAUDIO_AVAILABLE:
            on_error("pyaudio missing — pip install pyaudio")
            time.sleep(5)
            return

        if not self._model_ready:
            time.sleep(0.5)    # wait for model to finish loading
            return

        self._is_listening = True
        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS,
                             rate=SAMPLE_RATE, input=True,
                             frames_per_buffer=CHUNK_FRAMES)
            on_listening()

            # pre_buf: ring buffer of last 6 chunks (~0.4s) captured before
            # speech is detected. Included at the start of every utterance so
            # the first syllable ("st-" in "start") is never clipped.
            PRE_BUF_SIZE = 6
            pre_buf = []
            buf = []
            silence_t = None
            in_speech = False

            while self._is_enabled:
                try:
                    raw = stream.read(
                        CHUNK_FRAMES, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.02)
                    continue

                chunk = np.frombuffer(raw, dtype=np.int16)
                rms = math.sqrt(max(1, np.mean(chunk.astype(np.float32) ** 2)))

                if rms > SILENCE_RMS:
                    if not in_speech:
                        # Speech just started — prepend pre-buffer so first
                        # syllable is included even if it was below threshold
                        buf = list(pre_buf)
                    in_speech = True
                    silence_t = None
                    buf.append(chunk)
                    if len(buf) * CHUNK_FRAMES / SAMPLE_RATE >= MAX_SPEECH_SECS:
                        break
                elif in_speech:
                    buf.append(chunk)
                    if silence_t is None:
                        silence_t = time.time()
                    elif time.time() - silence_t >= SILENCE_SECS:
                        break   # segment complete
                else:
                    # Still in silence — maintain rolling pre-buffer
                    pre_buf.append(chunk)
                    if len(pre_buf) > PRE_BUF_SIZE:
                        pre_buf.pop(0)

            # Transcribe
            if buf and in_speech:
                secs = len(buf) * CHUNK_FRAMES / SAMPLE_RATE
                if secs >= MIN_SPEECH_SECS:
                    audio = np.concatenate(buf).astype(np.float32) / 32768.0
                    text = self._transcribe(audio)
                    if text:
                        print(f"[VoiceActivator] '{text}'")
                        if self._on_heard_callback:
                            try:
                                self._on_heard_callback(text)
                            except Exception:
                                pass
                        self._process_command(
                            text, on_mode_activated, on_command)

        except Exception as e:
            if self._is_enabled:
                on_error(f"Mic error: {e}")
                time.sleep(1)
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            pa.terminate()
            self._is_listening = False

    # ── Whisper ───────────────────────────────────────────────────────────────

    def _transcribe(self, audio_np):
        with self._model_lock:
            model = self._model
        if not model:
            return ""
        try:
            segments, _ = model.transcribe(
                audio_np,
                language="en",
                beam_size=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 200},
                no_speech_threshold=0.5,      # lower = less likely to discard real commands
                condition_on_previous_text=False,
                temperature=0.0,
            )
            # Only filter hallucinations — don't filter by logprob for short commands
            # Short phrases like "start cursor mode" have naturally lower logprob
            parts = [
                s.text.strip() for s in segments
                if s.text.strip().lower() not in HALLUCINATIONS
            ]
            return " ".join(parts).strip().lower()
        except Exception as e:
            print(f"[VoiceActivator] Transcription error: {e}")
            return ""

    # ── Command dispatch ──────────────────────────────────────────────────────

    def _process_command(self, text, on_mode_activated, on_command):
        t = text.lower().strip()

        for mode_id, kws in self.STOP_MODE_KEYWORDS.items():
            if any(kw in t for kw in kws):
                print(f"[VoiceActivator] Stop → {mode_id}")
                if self._on_mode_stopped_callback:
                    self._on_mode_stopped_callback(mode_id)
                return

        for mode_id, kws in self.MODE_KEYWORDS.items():
            if any(kw in t for kw in kws):
                print(f"[VoiceActivator] Activate → {mode_id}")
                on_mode_activated(mode_id)
                return

        for cmd, kws in self.OTHER_COMMANDS.items():
            if any(kw in t for kw in kws):
                print(f"[VoiceActivator] Command → {cmd}")
                on_command(cmd)
                return

        print(f"[VoiceActivator] Unrecognized: '{text}'")
        if self._on_unrecognized_callback:
            self._on_unrecognized_callback(text)

    @property
    def is_listening(self):
        return self._is_listening

    @property
    def is_enabled(self):
        return self._is_enabled
