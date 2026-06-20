"""
voice_handler.py — Voice Recognition for Web Mode (v4)
"""

import re
import threading
import time
import speech_recognition as sr
from typing import Callable, Optional


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "twenty one": 21, "twenty two": 22, "twenty three": 23, "twenty four": 24,
    "twenty five": 25, "twenty six": 26, "twenty seven": 27, "twenty eight": 28,
    "twenty nine": 29, "thirty": 30, "thirty one": 31, "thirty two": 32,
    "thirty three": 33, "thirty four": 34, "thirty five": 35, "thirty six": 36,
    "thirty seven": 37, "thirty eight": 38, "thirty nine": 39, "forty": 40,
    "forty one": 41, "forty two": 42, "forty three": 43, "forty four": 44,
    "forty five": 45, "forty six": 46, "forty seven": 47, "forty eight": 48,
    "forty nine": 49, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100,
}

URL_SUBS = {
    " dot com": ".com", " dot org": ".org", " dot net": ".net",
    " dot io": ".io", " dot edu": ".edu", " dot gov": ".gov",
    " dot ": ".", " slash ": "/", " colon ": ":",
    " dash ": "-", " underscore ": "_",
    " www ": "www.", "double u double u double u": "www",
}

PUNCT_WORDS = {
    " period ": ". ", " full stop ": ". ", " comma ": ", ",
    " exclamation mark ": "! ", " question mark ": "? ",
    " colon ": ": ", " semicolon ": "; ",
    " new line ": "\n", " newline ": "\n",
}

# All phrases that mean "stop web mode" — checked BEFORE search fallback
STOP_PHRASES = {
    "stop web mode", "exit web mode", "close web mode",
    "turn off web mode", "disable web mode", "quit web mode",
    "end web mode", "stop web", "turn off web", "kill web mode",
    "shut down web mode", "deactivate web mode",
}


class WebVoiceHandler:

    COMMANDS = {
        # Scroll
        "scroll down":      "scroll_down",
        "scroll up":        "scroll_up",
        "page down":        "scroll_down",
        "page up":          "scroll_up",
        "go to bottom":     "scroll_bottom",
        "go to top":        "scroll_top",
        "bottom":           "scroll_bottom",
        "top":              "scroll_top",

        # Browser navigation
        "go back":          "go_back",
        "back":             "go_back",
        "go forward":       "go_forward",
        "forward":          "go_forward",
        "refresh":          "refresh",
        "reload":           "refresh",
        "new tab":          "new_tab",
        "open new tab":     "new_tab",
        "close tab":        "close_tab",
        "next tab":         "next_tab",
        "previous tab":     "prev_tab",

        # Form / input
        "enter":            "enter",
        "press enter":      "enter",
        "submit":           "enter",
        "clear":            "clear_input",
        "clear field":      "clear_input",
        "delete that":      "clear_input",

        # Media controls
        "pause":            "media_pause",
        "play":             "media_play",
        "pause video":      "media_pause",
        "play video":       "media_play",
        "pause the video":  "media_pause",
        "play the video":   "media_play",
        "stop video":       "media_pause",
        "mute":             "media_mute",
        "unmute":           "media_mute",
        "mute video":       "media_mute",
        "unmute video":     "media_mute",
        "volume up":        "media_vol_up",
        "volume down":      "media_vol_down",
        "louder":           "media_vol_up",
        "quieter":          "media_vol_down",
        "fullscreen":       "media_fullscreen",
        "full screen":      "media_fullscreen",
        "exit fullscreen":  "media_fullscreen",
        "reveal controls":  "media_reveal",
        "show controls":    "media_reveal",
        "show player":      "media_reveal",

        # Labels
        "rescan":           "rescan",
        "scan page":        "rescan",
        "refresh labels":   "rescan",
        "show numbers":     "rescan",

        # Stop — all variants mapped here too (belt-and-suspenders)
        "stop web mode":        "stop",
        "exit web mode":        "stop",
        "close web mode":       "stop",
        "turn off web mode":    "stop",
        "disable web mode":     "stop",
        "quit web mode":        "stop",
        "end web mode":         "stop",
        "stop web":             "stop",
        "turn off web":         "stop",
        "kill web mode":        "stop",
        "shut down web mode":   "stop",
        "deactivate web mode":  "stop",
    }

    BASE_ENERGY = 400

    def __init__(
        self,
        on_click:    Callable[[int], None] = None,
        on_type:     Callable[[str], None] = None,
        on_navigate: Callable[[str], None] = None,
        on_command:  Callable[[str], None] = None,
        on_status:   Callable[[str], None] = None,
        on_error:    Callable[[str], None] = None,
    ):
        self.on_click = on_click or (lambda n: print(f"[Voice] Click #{n}"))
        self.on_type = on_type or (lambda t: print(f"[Voice] Type: {t}"))
        self.on_navigate = on_navigate or (
            lambda u: print(f"[Voice] Nav: {u}"))
        self.on_command = on_command or (lambda c: print(f"[Voice] Cmd: {c}"))
        self.on_status = on_status or (lambda s: print(f"[Voice] {s}"))
        self.on_error = on_error or (lambda e: print(f"[Voice] ERR: {e}"))

        self._stop_event = threading.Event()
        self._is_paused = False
        self._typing_mode = False

        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = self.BASE_ENERGY
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.pause_threshold = 0.6
        self.recognizer.non_speaking_duration = 0.4

    def start(self):
        self._stop_event.clear()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self._stop_event.set()

    def set_typing_mode(self, active: bool):
        self._typing_mode = active
        self.on_status(
            "⌨ Typing mode — speak to type, say 'enter' to submit"
            if active else "🎙 Listening for commands..."
        )

    def _listen_loop(self):
        while not self._stop_event.is_set():
            if self._is_paused:
                time.sleep(0.3)
                continue
            try:
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(
                        source, duration=0.5)
                    if self.recognizer.energy_threshold > 1000:
                        self.recognizer.energy_threshold *= 1.3
                    self.on_status("🎙 Listening...")
                    audio = self.recognizer.listen(
                        source, timeout=5, phrase_time_limit=10)
                threading.Thread(target=self._recognize,
                                 args=(audio,), daemon=True).start()
            except sr.WaitTimeoutError:
                pass
            except Exception as e:
                if not self._stop_event.is_set():
                    self.on_error(f"Mic error: {e}")
                    time.sleep(1)

    def _recognize(self, audio):
        try:
            text = self.recognizer.recognize_google(audio)
            print(f"[WebVoice] '{text}'")
            self.on_status(f'🗣 "{text}"')
            self._parse(text)
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            self.on_error(f"Speech service: {e}")

    def _parse(self, raw: str):
        text = raw.strip()
        lower = text.lower()

        # ── STOP CHECK — highest priority, checked before everything else ──
        # Check every stop phrase against the recognised text
        for phrase in STOP_PHRASES:
            if phrase in lower:
                print(f"[WebVoice] Stop matched: '{phrase}'")
                self.on_command("stop")
                return

        # Always-on enter — works even in typing mode to submit forms
        if lower in ("enter", "press enter", "submit"):
            self.on_command("enter")
            self.set_typing_mode(False)
            return

        # Typing mode — pass EVERYTHING as text, no URL/search parsing at all.
        # This is critical for email fields: "someone at gmail dot com" should
        # be typed, not navigated or searched.
        if self._typing_mode:
            typed = self._apply_punct(text)
            # Convert spoken email format: "at" → "@", "dot" → "."
            typed = re.sub(r'\s+at\s+', '@', typed)
            typed = re.sub(r'(?<=[a-z0-9])\s+dot\s+(?=[a-z])', '.', typed)
            self.on_type(typed)
            return

        # If the text looks like it contains an email address, type it directly
        # (handles case where user speaks an email without being in typing mode)
        if re.search(r'\b[a-z0-9._%+\-]+ at [a-z0-9.\-]+ dot [a-z]{2,}\b', lower):
            typed = re.sub(r'\s+at\s+', '@', text)
            typed = re.sub(
                r'(?<=[a-z0-9A-Z0-9])\s+dot\s+(?=[a-zA-Z])', '.', typed)
            self.on_type(typed)
            return

        # Named commands — longest match wins
        matched_cmd, matched_len = None, 0
        for phrase, cmd in self.COMMANDS.items():
            if phrase in lower and len(phrase) > matched_len:
                matched_cmd, matched_len = cmd, len(phrase)

        if matched_cmd:
            self.on_command(matched_cmd)
            return

        # "click N" / "number N" etc.
        # "click 7" / "number seven" / "open 12" etc.
        m = re.search(
            r'\b(?:click|number|select|press|open|choose|element|item)\s+(\d+|[a-z ]+?)\b',
            lower
        )
        if m:
            raw_num = re.sub(r'[^a-z0-9 ]', '', m.group(1)).strip()
            n = self._to_int(raw_num)
            if n is not None:
                self.on_click(n)
                return

        # Bare number — strip any trailing punctuation Whisper adds
        cleaned = re.sub(r'[^a-z0-9 ]', '', lower).strip()
        n = self._to_int(cleaned)
        if n is not None:
            self.on_click(n)
            return

        # URL
        url = self._to_url(lower)
        if url:
            self.on_navigate(url)
            return

        # Search fallback — only for multi-word phrases that don't look like
        # email addresses or other typed content
        words = text.split()
        if len(words) >= 2 and "at" not in lower.split():
            self.on_navigate(
                f"https://www.google.com/search?q={'+'.join(words)}")
        elif len(words) >= 2:
            # "at" in the phrase likely means an email — type it instead
            self.on_type(text)

    def _to_int(self, text: str) -> Optional[int]:
        # Strip Whisper punctuation (e.g. "seven." → "seven", "7." → "7")
        text = re.sub(r'[^a-z0-9 ]', '', text.strip().lower()).strip()
        if text.isdigit():
            return int(text)
        if text in NUMBER_WORDS:
            return NUMBER_WORDS[text]
        # "twenty one" style
        parts = text.split()
        if len(parts) == 2 and parts[0] in NUMBER_WORDS and parts[1] in NUMBER_WORDS:
            return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[1]]
        # Handle teens and tens as single digit strings e.g. "14" split weirdly
        if len(parts) > 0 and parts[-1].isdigit():
            return int(parts[-1])
        return None

    def _to_url(self, text: str) -> Optional[str]:
        t = " " + text.lower() + " "
        for spoken, actual in URL_SUBS.items():
            t = t.replace(spoken, actual)
        t = t.strip()
        if re.match(r'^[a-z0-9\-]+\.[a-z]{2,}', t):
            return ('https://' + t) if not t.startswith('http') else t
        if re.search(r'\.[a-z]{2,}(/|$)', t):
            return ('https://' + t) if not t.startswith('http') else t
        return None

    def _apply_punct(self, text: str) -> str:
        t = " " + text + " "
        for spoken, sym in PUNCT_WORDS.items():
            t = t.replace(spoken, sym)
        return t.strip()
