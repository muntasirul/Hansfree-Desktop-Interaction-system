# 🖥️ Desktop Navigation System
### CSE499 — Hands-Free Computer Control for Users Without Hands

A full accessibility platform that lets users control their entire computer — cursor, files, typing, and web browsing — using only their face, head movements, and voice. No keyboard or mouse required.

Built with Python, CustomTkinter, MediaPipe, faster-whisper, and a Chrome extension.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Modes](#modes)
  - [Cursor Navigation](#-cursor-navigation-mode)
  - [Action Mode](#-action-mode-ai-file-commander)
  - [Typing Mode](#-typing-mode)
  - [Web Mode](#-web-mode)
- [AI Models Used](#ai-models-used)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Setup](#setup)
- [How to Use](#how-to-use)
- [Voice Commands Reference](#voice-commands-reference)
- [The Whisper Bar](#the-whisper-bar-overlay)
- [Auto Typing Mode](#auto-typing-mode)
- [Configuration](#configuration)

---

## Overview

The Desktop Navigation System is a hands-free accessibility tool designed for users who cannot use a keyboard or mouse. The system is controlled entirely through:

- **Head and facial movements** — for cursor control
- **Voice commands** — for activating modes, typing, browsing, and managing files
- **Automatic focus detection** — typing mode activates when a text field is focused

All speech recognition runs **100% offline** using faster-whisper. No internet connection is required for any voice features. The only cloud service used is the Groq LLM API, and only for the AI file commander (optional).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    launcher.py                          │
│              Central Hub (CustomTkinter)                │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │VoiceMode    │  │FocusWatcher │  │  WhisperBar    │  │
│  │Activator    │  │(UIAutomation│  │  Overlay       │  │
│  │(tiny.en)    │  │ polling)    │  │  (top of screen│  │
│  └──────┬──────┘  └──────┬──────┘  └────────────────┘  │
│         │                │                              │
└─────────┼────────────────┼──────────────────────────────┘
          │ voice command  │ text field focused
          ▼                ▼
┌──────────────────────────────────────────────────────────┐
│              Mode Subprocesses (each isolated)          │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │Cursor/       │  │typing_mode/  │  │web_mode/      │  │
│  │gesture_      │  │main.py       │  │main.py        │  │
│  │pilot.py      │  │              │  │               │  │
│  │              │  │TypingEngine  │  │WebSocket      │  │
│  │MediaPipe     │  │(small.en)    │  │Server :9765   │  │
│  │FaceMesh      │  │3-thread      │  │               │  │
│  │468 landmarks │  │pipeline      │  │  ┌────────────┤  │
│  └──────────────┘  └──────────────┘  │  │Chrome Ext  │  │
│                                      │  │content.js  │  │
│  ┌──────────────┐                    │  │background  │  │
│  │file_commander│                    └──┴────────────┘  │
│  │AIHandler     │                                        │
│  │(Groq LLM)    │                                        │
│  └──────────────┘                                        │
└──────────────────────────────────────────────────────────┘
```

### Key design decisions

- **Subprocess isolation** — each mode runs as a separate Python subprocess so a crash in one mode never takes down the launcher or other modes.
- **Mic exclusivity** — Web Mode and Typing Mode take ownership of the microphone when active. The launcher's voice activator pauses and resumes automatically.
- **Offline-first** — all speech recognition (both mode activation and dictation) uses faster-whisper locally. The only network call is to Groq for file commands.
- **FocusWatcher** — a background thread polls Windows UIAutomation every 500 ms to detect when the user clicks into a text field, triggering Typing Mode automatically without any voice command.

---

## Modes

### 🎯 Cursor Navigation Mode

Controls the mouse cursor using the user's nose tip position tracked by the webcam.

**Technology:** MediaPipe FaceMesh (468 facial landmarks), OpenCV, PyAutoGUI

**How it works:**
- Webcam feed is processed frame-by-frame by MediaPipe FaceMesh
- Nose tip landmark position is mapped to screen coordinates
- Acceleration curve (`ACCELERATION_POWER = 2.75`) makes small head movements precise while large movements are fast
- A deadzone in the centre prevents cursor drift when the user is still

**Gesture controls:**

| Gesture | Action |
|---|---|
| Move head | Move cursor |
| Single blink | Left click |
| Double blink (within 1.5s) | Double click |
| Blink + hold 1 second | Right click |
| Open mouth briefly | Left click (alternative) |
| `S` key | Toggle scroll mode |
| `Q` key | Quit |

---

### ⚡ Action Mode (AI File Commander)

Execute file system operations and launch applications using natural language voice or text input.

**Technology:** Groq API → LLaMA 3.3 70B, PyAutoGUI, Python `os`/`shutil`

**How it works:**
- User speaks or types a natural language command
- The command is sent to Groq (LLaMA 3.3 70B) which converts it to structured JSON
- A local executor parses the JSON and runs the corresponding file operation

**Supported operations:**
`copy`, `move`, `delete`, `list`, `rename`, `create_folder`, `create_file`, `open`, `launch_app`, `close_app`, `write_file`

**Example commands:**
```
"Create a folder called Projects on my Desktop"
"Move all PDF files from Downloads to Documents"
"Open Chrome"
"Delete the file report_draft.txt"
```

---

### ⌨️ Typing Mode

Continuous offline voice dictation that types into any focused application — Word, Notepad, browser search bars, VS Code, anywhere.

**Technology:** faster-whisper `small.en`, PyAudio, PyAutoGUI / pyperclip

**3-thread pipeline:**
```
Mic (PyAudio) ──► Audio Queue ──► Whisper ──► Text Queue ──► Typer
   Thread 1                      Thread 2                  Thread 3
```

- **Thread 1** (`_mic_loop`): Opens PyAudio stream, applies RMS energy VAD to detect speech vs silence, flushes completed segments to the audio queue
- **Thread 2** (`_recognizer_loop`): Pulls audio clips, runs `WhisperModel.transcribe()`, filters hallucinations, pushes clean text to the text queue
- **Thread 3** (`_typer_loop`): Pulls text, parses voice commands vs plain dictation, types into the active window using pyautogui

**Built-in voice commands (while dictating):**

| Say | Action |
|---|---|
| `"new line"` | Press Enter |
| `"delete that"` | Delete last word |
| `"period"` / `"full stop"` | Type `.` |
| `"comma"` | Type `,` |
| `"question mark"` | Type `?` |
| `"exclamation mark"` | Type `!` |
| `"stop typing"` | Exit typing mode |

---

### 🌐 Web Mode

Browse the web hands-free using voice commands. Works with Chrome and Edge.

**Technology:** Python WebSocket server (`ws://localhost:9765`), Chrome Extension (Manifest V3), faster-whisper `tiny.en`

**Architecture:**
```
Voice ──► Python Parser ──► WebSocket ──► Chrome Extension ──► DOM
          (web_mode/          :9765        background.js
           voice_handler.py)              content.js
```

**How it works:**
1. Python starts a WebSocket server on `localhost:9765`
2. The Chrome extension (`web_mode/extension/`) connects automatically
3. `content.js` scans the DOM and injects numbered badges on every clickable element
4. Voice commands are parsed in Python and sent as JSON actions over WebSocket
5. The extension executes the action directly in the browser

**Badge colours:**
- 🔵 Cyan = Button
- 🟢 Green = Input field
- 🟣 Purple = Link
- 🟡 Yellow = Media element

**Voice commands:**

| Say | Action |
|---|---|
| `"7"` (any number) | Click element with that badge number |
| `"scroll down"` / `"scroll up"` | Scroll the page |
| `"go back"` / `"go forward"` | Browser history |
| `"new tab"` | Open new tab |
| `"youtube dot com"` | Navigate to URL |
| `"how to make pizza"` | Google search |
| `"enter"` | Submit / press Enter |
| `"rescan"` | Refresh element labels |
| `"pause"` / `"play"` | Direct `video.play()` / `video.pause()` |
| `"mute"` | Toggle `video.muted` |
| `"volume up"` / `"volume down"` | Adjust `video.volume` ±0.1 |
| `"fullscreen"` | `requestFullscreen()` |
| `"stop web mode"` | Exit web mode |

---

## AI Models Used

| Model | Used In | Size | Runs |
|---|---|---|---|
| **faster-whisper `tiny.en`** | Voice Mode Activator (launcher keyword detection) | 75 MB | Offline / CPU |
| **faster-whisper `small.en`** | Typing Mode dictation engine | 244 MB | Offline / CPU |
| **MediaPipe FaceMesh** | Cursor Navigation (468 facial landmark tracking) | ~30 MB | Offline / CPU |
| **Groq — LLaMA 3.3 70B** | Action Mode file command parsing (primary) | Cloud | API |
| **Groq — LLaMA 3 8B** | Action Mode file command parsing (fallback) | Cloud | API |

> **Note:** All voice and vision processing is fully offline. Groq is only used for the AI File Commander. The system works without internet except for that one feature.

Both faster-whisper models download automatically on first run from Hugging Face and are cached at `~/.cache/huggingface/hub/`. Subsequent starts load instantly from cache.

---

## Project Structure

```
CSE499/
│
├── launcher.py                  # Main hub — CustomTkinter UI, mode orchestration
├── assistant.py                 # NavigationAssistant — Groq LLM + pyttsx3 TTS
├── voice_mode_activator.py      # Launcher voice: faster-whisper tiny.en keyword detection
├── focus_watcher.py             # UIAutomation polling — auto-starts Typing Mode on text focus
├── whisper_bar.py               # Always-on-top overlay showing Whisper transcriptions
├── .env                         # GROQ_API_KEY goes here
├── requirements.txt
│
├── Cursor/
│   └── gesture_pilot.py         # MediaPipe FaceMesh cursor control + gesture clicks
│
├── typing_mode/
│   ├── main.py                  # Typing Mode entry point + overlay
│   ├── typing_engine.py         # faster-whisper small.en, 3-thread VAD→transcribe→type
│   └── overlay.py               # Floating status overlay
│
├── web_mode/
│   ├── main.py                  # Web Mode entry point
│   ├── websocket_server.py      # Async WebSocket server on ws://localhost:9765
│   ├── voice_handler.py         # Web Mode voice parser (stop phrases, numbers, URLs)
│   ├── overlay.py               # Web Mode floating overlay
│   └── extension/
│       ├── manifest.json        # Chrome Extension MV3 manifest
│       ├── background.js        # Service worker — WebSocket ↔ Chrome tabs bridge
│       ├── content.js           # DOM scanner, badge injector, action executor
│       ├── popup.html           # Extension popup — shows connection status
│       └── popup.js
│
└── file_commander/
    ├── ai_handler.py            # Groq LLaMA 3.3 70B — natural language → JSON actions
    ├── file_ops.py              # JSON action executor (copy, move, delete, open, etc.)
    ├── voice_handler.py         # File commander voice input
    └── gui.py                   # File commander UI
```

---

## Installation

### Requirements

- Python 3.10+
- Windows 10/11 (UIAutomation and some features are Windows-specific)
- A webcam (for Cursor Mode)
- A microphone
- Google Chrome or Microsoft Edge (for Web Mode)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/CSE499.git
cd CSE499
```

### 2. Install Python dependencies

```bash
pip install customtkinter
pip install faster-whisper
pip install pyaudio
pip install numpy
pip install mediapipe
pip install opencv-python
pip install pyautogui
pip install pyperclip
pip install pyttsx3
pip install groq
pip install python-dotenv
pip install websockets
pip install uiautomation
pip install SpeechRecognition
```

Or install from requirements.txt (add the new packages):

```bash
pip install -r requirements.txt
pip install faster-whisper uiautomation websockets numpy
```

### 3. Suppress the Windows symlink warning (optional)

faster-whisper shows a harmless warning about symlinks on Windows. To disable it permanently:

```powershell
[System.Environment]::SetEnvironmentVariable("HF_HUB_DISABLE_SYMLINKS_WARNING", "1", "User")
```

### 4. Set up your Groq API key (for Action Mode only)

Create a `.env` file in the `CSE499/` root folder:

```
GROQ_API_KEY=your_key_here
```

Get a free API key at [console.groq.com](https://console.groq.com). The rest of the system works without it.

### 5. Install the Chrome Extension (for Web Mode)

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `CSE499/web_mode/extension/` folder
5. The extension appears with a cyan badge when Web Mode is running

---

## Setup

### First run — model downloads

On the very first launch, faster-whisper will download two models:

| Model | Size | Used for |
|---|---|---|
| `tiny.en` | 75 MB | Launcher keyword detection |
| `small.en` | 244 MB | Typing Mode dictation |

Both download automatically to `~/.cache/huggingface/hub/` and load from cache instantly on all subsequent runs. You will see:

```
[VoiceActivator] Loading faster-whisper tiny.en...
[VoiceActivator] ✓ Model ready
```

and in Typing Mode:

```
[TypingEngine] Loading faster-whisper small.en on cpu…
[TypingEngine] ✓ Model ready
```

---

## How to Use

### Start the launcher

```bash
cd CSE499
python launcher.py
```

The main hub window opens (920×820 dark UI) and the **Whisper Bar** overlay appears at the top centre of your screen.

### Activate modes

You can activate any mode by either:
- **Clicking** the mode card in the launcher UI
- **Saying** the mode name out loud

The launcher listens continuously. Speak clearly and wait for the Whisper Bar to show what it heard.

#### Voice activation phrases

| Say | Activates |
|---|---|
| `"cursor mode"` | Cursor Navigation |
| `"action mode"` | AI File Commander |
| `"typing mode"` | Voice Dictation |
| `"web mode"` | Web Browser Control |

#### Voice stop phrases

| Say | Stops |
|---|---|
| `"stop cursor mode"` / `"close cursor"` | Cursor Mode |
| `"stop action mode"` / `"close action"` | Action Mode |
| `"stop typing mode"` / `"exit typing"` | Typing Mode |
| `"stop web mode"` / `"exit web mode"` | Web Mode |

### Mic exclusivity

Web Mode and Typing Mode take ownership of the microphone while active. When either is running the launcher's voice activator pauses automatically. When the mode stops, the launcher resumes listening.

---

## Voice Commands Reference

### Launcher (always listening when no exclusive mode is active)

```
"cursor mode"          → start Cursor Navigation
"action mode"          → start AI File Commander
"typing mode"          → start Typing Mode
"web mode"             → start Web Mode
"stop [mode] mode"     → stop a specific mode
"help"                 → display help information
"stop all"             → stop all running modes
```

### Typing Mode (while dictating)

```
"new line"             → Enter key
"delete that"          → delete last word
"period"               → .
"comma"                → ,
"question mark"        → ?
"exclamation mark"     → !
"open bracket"         → (
"close bracket"        → )
"stop typing"          → exit typing mode
```

### Web Mode (while browsing)

```
[number]               → click element with that number
"scroll down/up"       → scroll page
"go back/forward"      → browser history
"refresh"              → reload page
"new tab"              → open new tab
"close tab"            → close current tab
"next tab/prev tab"    → switch tabs
[website].com          → navigate to URL  e.g. "youtube dot com"
[search query]         → Google search    e.g. "best python tutorials"
"enter"                → press Enter / submit
"rescan"               → refresh clickable labels
"pause" / "play"       → video playback
"mute"                 → toggle video mute
"volume up/down"       → adjust video volume
"fullscreen"           → enter fullscreen
"stop web mode"        → exit web mode
```

---

## The Whisper Bar Overlay

A slim 480×46 px bar appears at the top-centre of the screen whenever the launcher is running. It shows in real time what the voice activator hears.

| Dot colour | Meaning |
|---|---|
| 🟡 Yellow (static) | Whisper model is loading |
| 🟢 Green (pulsing) | Mic is open, listening |
| 🔵 Blue | Transcription just received — shown for 4 seconds |

**Controls:**
- **Drag** anywhere on the bar to reposition it
- **Double-click** to minimise it out of the way

---

## Auto Typing Mode

Typing Mode activates automatically when you click into any text field — no voice command needed. This is powered by `focus_watcher.py` which uses the Windows UIAutomation API.

**Supported applications:**
- Microsoft Word (paragraphs, text boxes)
- Notepad, Notepad++
- Browser address bars and search fields (Chrome, Edge, Firefox)
- VS Code editor
- Any standard Windows Edit or RichEdit control

**Behaviour:**
- Focus enters a text field → Typing Mode starts immediately
- Focus leaves the text field → Typing Mode stops after a 1.5-second debounce delay (prevents flickering when clicking the title bar, scrollbar, or ribbon)
- If you manually started Typing Mode yourself via voice or the card button, clicking outside will NOT auto-stop it

---

## Configuration

Key settings you can tune per file:

### `voice_mode_activator.py`
```python
WHISPER_MODEL   = "tiny.en"   # "small.en" for better accuracy, slower
SILENCE_RMS     = 350         # raise if background noise triggers false commands
SILENCE_SECS    = 0.6         # pause duration that ends a phrase
```

### `typing_mode/typing_engine.py`
```python
WHISPER_MODEL   = "small.en"  # "medium.en" for higher accuracy
SILENCE_RMS     = 500         # raise if mic picks up keyboard or ambient noise
SILENCE_SECS    = 1.2         # longer = waits more before transcribing
```

### `focus_watcher.py`
```python
POLL_INTERVAL           = 0.5    # how often to check focus (seconds)
self._leave_debounce_secs = 1.5  # how long focus must be away before stopping typing
```

### `Cursor/gesture_pilot.py`
```python
BASE_SPEED          = 200     # cursor speed multiplier
ACCELERATION_POWER  = 2.75    # higher = faster acceleration on large movements
DEADZONE_NORM       = 0.08    # larger = more head movement needed before cursor moves
BLINK_EAR_THRESH    = 0.045   # lower = more sensitive blink detection
```

---

## Known Limitations

- **Windows only** — FocusWatcher uses Windows UIAutomation. Cursor and Typing modes use PyAutoGUI which works cross-platform, but the auto-focus detection does not.
- **CPU inference** — Whisper runs on CPU by default. If you have an NVIDIA GPU, set `WHISPER_DEVICE = "cuda"` in both engine files for significantly faster transcription.
- **Web Mode browser support** — only Chrome and Chromium-based Edge are supported (Chrome Extension MV3).
- **Accent sensitivity** — `tiny.en` may struggle with strong accents on short commands. Switch to `small.en` in `voice_mode_activator.py` for better accuracy at the cost of ~0.5s more latency.
- **Groq rate limits** — the free Groq tier has request limits. Action Mode falls back automatically from LLaMA 3.3 70B to LLaMA 3 8B when rate limited.

---

## Potential Improvement Research

- **Faster local inference** — benchmark quantized Whisper (`int8`/`int4` GGML or ONNX) and CUDA builds to shrink Typing Mode latency without sacrificing accuracy.
- **Robust noise handling** — evaluate lightweight denoisers (RNNoise, WebRTC VAD) before Whisper to reduce false activations from fans/keyboard clicks; tune `SILENCE_RMS`/`SILENCE_SECS` with recorded noisy datasets.
- **Cross-platform focus detection** — prototype macOS/Linux equivalents to `FocusWatcher` (e.g., PyObjC Accessibility API or AT-SPI) to remove the Windows-only limitation while keeping the same debounce behavior.
- **Cursor calibration UX** — add a short onboarding flow that measures the user’s neutral head pose and adapts `DEADZONE_NORM`/`ACCELERATION_POWER` automatically for steadier cursor control.
- **Offline Action Mode** — investigate on-device LLMs (e.g., LLaMA 3 8B quantized) as a fallback when Groq is unavailable, keeping the existing JSON action schema for compatibility.
- **Multi-language voice support** — test Whisper multilingual checkpoints for activation and dictation, plus language auto-detection, to improve accuracy for non-English users.

---

## Tech Stack Summary

| Component | Technology |
|---|---|
| UI Framework | CustomTkinter (dark theme) |
| Voice (keywords) | faster-whisper `tiny.en` + PyAudio |
| Voice (dictation) | faster-whisper `small.en` + PyAudio |
| Face/cursor tracking | MediaPipe FaceMesh + OpenCV |
| LLM (file commands) | Groq API — LLaMA 3.3 70B / LLaMA 3 8B |
| TTS (launcher) | pyttsx3 |
| Browser integration | Chrome Extension MV3 + WebSocket |
| Focus detection | Windows UIAutomation (`uiautomation`) |
| Typing output | PyAutoGUI + pyperclip |

---

*CSE499 — Senior Design Project*
