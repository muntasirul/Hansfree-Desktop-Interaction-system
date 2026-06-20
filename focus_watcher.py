"""
focus_watcher.py — Auto-activate Typing Mode when user focuses a text field.

HOW IT WORKS
────────────
A background thread polls every 500 ms using the Windows UI Automation API
(via the `uiautomation` library). It checks what UI element currently has
keyboard focus. If that element is an editable text control (a text box,
search bar, address bar, Word paragraph, etc.) it fires on_text_field_focused().
When focus moves away from a text control it fires on_text_field_lost().

The launcher connects these two callbacks to _auto_start_typing() and
_auto_stop_typing() — starting/stopping typing mode exactly like clicking
the card button, but without any voice command needed.

SUPPORTED APPLICATIONS (auto-detected)
───────────────────────────────────────
  • Chrome / Edge address bar and search boxes
  • Firefox address bar and web page inputs
  • Word, Notepad, Notepad++, VS Code editors
  • Any standard Windows text field (Edit, RichEdit, UIA TextEdit controls)

INSTALL
───────
    pip install uiautomation

uiautomation uses the native Windows UIAutomation API — no extra drivers needed.
Requires Python 3.x on Windows.
"""

import threading
import time
from typing import Callable, Optional

# ── Windows UIAutomation ──────────────────────────────────────────────────────
try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    print("[FocusWatcher] MISSING: uiautomation — run: pip install uiautomation")


# Control types that count as "editable text field"
TEXT_CONTROL_TYPES = {
    auto.ControlType.EditControl if UIA_AVAILABLE else 50004,   # single-line text box
    # Word / rich text editors
    auto.ControlType.DocumentControl if UIA_AVAILABLE else 50030,
}

# Applications to SKIP — their text areas don't need dictation
# (add window title substrings here to exclude specific apps)
EXCLUDED_WINDOW_TITLES = {
    "desktop navigation",   # our own launcher
    "typing mode",          # typing mode overlay itself
    "web mode",
    "visual studio code",  # Add this to stop the flicker in VS Code
    "vscode",            # web mode overlay
}

# How often to check focus (seconds)
POLL_INTERVAL = 0.5


class FocusWatcher:
    """
    Polls the Windows focus every POLL_INTERVAL seconds.
    Calls on_enter when focus lands on a text field,
    calls on_leave when focus moves away.

    Usage in launcher:
        watcher = FocusWatcher(
            on_enter=self._auto_start_typing,
            on_leave=self._auto_stop_typing,
        )
        watcher.start()
    """

    def __init__(
        self,
        on_enter: Callable[[], None],   # called when text field focused
        on_leave: Callable[[], None],   # called when focus leaves text field
    ):
        self._on_enter = on_enter
        self._on_leave = on_leave
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._in_text_field = False

        # Debounce: don't fire on_leave until focus has been away for this long.
        # Prevents flicker when clicking scrollbar, title bar, ribbon, etc.
        self._leave_debounce_secs = 1.5
        self._leave_timer: Optional[threading.Timer] = None

    def start(self):
        """Start the background polling thread."""
        if not UIA_AVAILABLE:
            print("[FocusWatcher] uiautomation not installed — auto-typing disabled")
            return

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="focus-watcher")
        self._thread.start()
        print("[FocusWatcher] Started")

    def stop(self):
        """Stop polling."""
        self._running = False

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                self._check_focus()
            except Exception as e:
                # UIA can raise COM errors on some windows — ignore silently
                pass
            time.sleep(POLL_INTERVAL)

    def _check_focus(self):
        """
        Get the currently focused UI element.
        Determine if it is an editable text control.
        Fire callbacks on state transitions.
        """
        try:
            focused = auto.GetFocusedControl()
        except Exception:
            return

        if focused is None:
            self._set_in_field(False)
            return

        # Check if the focused control is a text-editable type
        ctrl_type = getattr(focused, "ControlType", None)
        is_text = ctrl_type in TEXT_CONTROL_TYPES

        # Also accept any control that has the ValuePattern or TextPattern
        # (catches browser address bars which are ControlType.Edit)
        if not is_text:
            try:
                patterns = focused.GetSupportedPatterns()
                pattern_ids = {
                    p.patternId for p in patterns} if patterns else set()
                # ValuePatternId=10002, TextPatternId=10014
                is_text = (10002 in pattern_ids or 10014 in pattern_ids)
            except Exception:
                pass

        # Check the window title is not one of our own excluded windows
        if is_text:
            try:
                win_title = focused.GetTopLevelControl().Name.lower()
                if any(excl in win_title for excl in EXCLUDED_WINDOW_TITLES):
                    is_text = False
            except Exception:
                pass

        # Also check if the element is read-only (skip read-only text views)
        if is_text:
            try:
                is_readonly = focused.GetValuePattern().IsReadOnly
                if is_readonly:
                    is_text = False
            except Exception:
                pass   # no ValuePattern = not a simple input, keep as-is

        self._set_in_field(is_text)

    def _set_in_field(self, now_in_field: bool):
        """
        Fire callbacks on state transition with debounce on leave.

        ENTER: fires immediately — start typing right away.
        LEAVE:  waits _leave_debounce_secs before firing — if focus returns
                within that window (e.g. clicking scrollbar, ribbon, title bar)
                the leave is cancelled and typing continues uninterrupted.
        """
        if now_in_field:
            # Cancel any pending leave timer — focus came back
            if self._leave_timer is not None:
                self._leave_timer.cancel()
                self._leave_timer = None

            if not self._in_text_field:
                self._in_text_field = True
                print("[FocusWatcher] → Text field focused — starting Typing Mode")
                try:
                    self._on_enter()
                except Exception as e:
                    print(f"[FocusWatcher] on_enter error: {e}")

        else:
            # Only start the leave timer if we're currently in a text field
            if self._in_text_field and self._leave_timer is None:
                self._leave_timer = threading.Timer(
                    self._leave_debounce_secs, self._fire_leave)
                self._leave_timer.daemon = True
                self._leave_timer.start()

    def _fire_leave(self):
        """Actually fire on_leave after debounce period has elapsed."""
        self._leave_timer = None
        if not self._in_text_field:
            return   # already handled
        self._in_text_field = False
        print("[FocusWatcher] → Focus left text field — stopping Typing Mode")
        try:
            self._on_leave()
        except Exception as e:
            print(f"[FocusWatcher] on_leave error: {e}")

    @property
    def is_in_text_field(self) -> bool:
        return self._in_text_field
