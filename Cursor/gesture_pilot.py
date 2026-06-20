import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import time
import keyboard
import subprocess
import ctypes
import ctypes.wintypes

# ───────── CAMERA SETTINGS ─────────
CAMERA_INDEX = 1
CAMERA_WIDTH = 1200
CAMERA_HEIGHT = 720

# ───────── CURSOR SETTINGS ─────────
BASE_SPEED = 200
ACCELERATION_POWER = 2.75
DEADZONE_NORM = 0.08

# ───────── BLINK SETTINGS ─────────
BLINK_EAR_THRESH = 0.045
RIGHT_CLICK_HOLD = 1.0   # seconds hold = right click
BLINK_MIN_DURATION = 0.04  # ignore EAR flicker shorter than 40ms
BLINK_COOLDOWN = 0.15  # min gap between two registered blinks

# ── NEW: double-blink → double click ────────────────────────────────────────
# DOUBLE_BLINK_WINDOW : after 1st blink, how long (sec) to wait for 2nd blink
DOUBLE_BLINK_WINDOW = 1.5
# BLINK_MAX_SHORT     : blink must be shorter than this to count (not a hold)
BLINK_MAX_SHORT = 0.4

# ───────── MOUTH SETTINGS ─────────
MOUTH_OPEN_THRESH = 0.38
MOUTH_MIN_MS = 80
MOUTH_MAX_MS = 600
MOUTH_COOLDOWN = 0.5

# ───────── SCROLL SETTINGS ─────────
SMILE_THRESH = 0.55
SCROLL_COOLDOWN = 0.12


# ───────── INITIALIZE ─────────
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

pyautogui.FAILSAFE = False
screen_w, screen_h = pyautogui.size()


# ───────── UTILITY FUNCTIONS ─────────
def dist(p1, p2):
    return np.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


def mouth_ratio(lm, eye_d):
    return dist(lm[13], lm[14]) / (eye_d + 1e-6)


def mouth_width(lm, eye_d):
    return dist(lm[61], lm[291]) / (eye_d + 1e-6)


def eye_ratio(lm, eye_d):
    l = dist(lm[159], lm[145]) / eye_d
    r = dist(lm[386], lm[374]) / eye_d
    return (l + r) / 2.0


# ───────── ON-SCREEN KEYBOARD HELPER ─────────────────────────────────────────
# The on-screen keyboard (osk.exe) runs at UIAccess privilege level.
# Normal pyautogui clicks on its title bar don't work.
# Solution: toggle it using the Windows API directly.

def _find_osk_window():
    """Return HWND of the on-screen keyboard window, or None."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW("OSKMainClass", None)
    if not hwnd:
        # Windows 10/11 uses a different class name
        hwnd = user32.FindWindowW(
            "Windows.UI.Core.CoreWindow", "On-Screen Keyboard")
    return hwnd if hwnd else None


def toggle_osk():
    """
    Toggle the on-screen keyboard.
    If it's open → close it.
    If it's closed → open it.
    Uses Win32 API so it works even though osk.exe runs at UIAccess level.
    """
    hwnd = _find_osk_window()
    if hwnd:
        # OSK is open — close it with WM_CLOSE (value 0x0010)
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        print("[Cursor] On-screen keyboard closed")
    else:
        # OSK is closed — launch it
        subprocess.Popen(['osk.exe'], shell=True)
        print("[Cursor] On-screen keyboard opened")


# ───────── MAIN ─────────
def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    smooth_x = screen_w // 2
    smooth_y = screen_h // 2
    center_x = None
    center_y = None

    # ── Blink tracking ───────────────────────────────────────────────────────
    eyes_closed = False
    eye_close_start = 0.0
    right_click_triggered = False
    last_blink_reg = 0.0  # cooldown guard

    # blink_times: rolling list of timestamps of completed short blinks
    # Logic: once 1st blink lands → start 3-sec timer
    #        if 2nd blink arrives within DOUBLE_BLINK_WINDOW → double click
    #        if timer expires with only 1 blink → nothing (no accidental click)
    blink_times = []

    # ── Mouth ────────────────────────────────────────────────────────────────
    mouth_start = None
    last_mouth_time = 0.0

    # ── Scroll ───────────────────────────────────────────────────────────────
    scroll_enabled = False
    last_scroll_time = 0.0

    print("Gestures:")
    print("  Blink twice (within 3s) → Double click")
    print("  Blink + hold 1 sec      → Right click")
    print("  Open mouth briefly      → Left click")
    print("  S                       → Toggle scroll mode")
    print("  K                       → Toggle on-screen keyboard")
    print("  Q                       → Quit")

    frame_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)
        now = time.time()

        if results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark
            nx = lm[4].x
            ny = lm[4].y
            eye_d = dist(lm[33], lm[263])

            if center_x is None:
                center_x, center_y = nx, ny

            # ── CURSOR ──────────────────────────────────────────────────────
            offset_x = (nx - center_x) / (eye_d + 1e-6)
            offset_y = (ny - center_y) / (eye_d + 1e-6)
            if abs(offset_x) < DEADZONE_NORM:
                offset_x = 0
            if abs(offset_y) < DEADZONE_NORM:
                offset_y = 0

            vx = np.sign(offset_x) * (abs(offset_x) **
                                      ACCELERATION_POWER) * BASE_SPEED
            vy = np.sign(offset_y) * (abs(offset_y) **
                                      ACCELERATION_POWER) * BASE_SPEED
            smooth_x = np.clip(smooth_x + vx, 0, screen_w - 1)
            smooth_y = np.clip(smooth_y + vy, 0, screen_h - 1)
            pyautogui.moveTo(int(smooth_x), int(smooth_y))

            # ── BLINK STATE MACHINE ─────────────────────────────────────────
            ear = eye_ratio(lm, eye_d)

            if ear < BLINK_EAR_THRESH:
                # Eyes CLOSING
                if not eyes_closed:
                    eyes_closed = True
                    eye_close_start = now
                    right_click_triggered = False

                # Long hold → right click
                if not right_click_triggered and (now - eye_close_start) >= RIGHT_CLICK_HOLD:
                    pyautogui.rightClick()
                    right_click_triggered = True
                    blink_times.clear()   # cancel any pending double-click
                    print("Right click")

            else:
                # Eyes OPEN
                if eyes_closed:
                    eyes_closed = False
                    blink_dur = now - eye_close_start

                    # Count as a valid short blink if:
                    #  • right-click was NOT triggered (not a hold)
                    #  • blink duration is real (>= 40ms, not EAR flicker)
                    #  • blink duration is short (<= BLINK_MAX_SHORT, not a hold)
                    #  • cooldown has passed
                    if (not right_click_triggered
                            and BLINK_MIN_DURATION <= blink_dur <= BLINK_MAX_SHORT
                            and (now - last_blink_reg) >= BLINK_COOLDOWN):
                        blink_times.append(now)
                        last_blink_reg = now
                        print(
                            f"Blink registered ({len(blink_times)} in window)")

                    right_click_triggered = False

                # Expire blinks outside the 3-sec window
                blink_times = [t for t in blink_times if now -
                               t <= DOUBLE_BLINK_WINDOW]

                # 2 blinks within window → double click
                if len(blink_times) >= 2:
                    pyautogui.doubleClick()
                    blink_times.clear()
                    print("Double click")

            # ── MOUTH → LEFT CLICK ───────────────────────────────────────────
            mr = mouth_ratio(lm, eye_d)
            if mr > MOUTH_OPEN_THRESH:
                if mouth_start is None:
                    mouth_start = now
            else:
                if mouth_start is not None:
                    dur_ms = (now - mouth_start) * 1000
                    if MOUTH_MIN_MS < dur_ms < MOUTH_MAX_MS:
                        if now - last_mouth_time > MOUTH_COOLDOWN:
                            pyautogui.click()
                            last_mouth_time = now
                            print("Left click")
                    mouth_start = None

            # ── SCROLL ───────────────────────────────────────────────────────
            if scroll_enabled:
                mw = mouth_width(lm, eye_d)
                if mw > SMILE_THRESH and abs(offset_y) > 0.06:
                    if now - last_scroll_time > SCROLL_COOLDOWN:
                        pyautogui.scroll(int(-offset_y * 300))
                        last_scroll_time = now

        # ── KEYBOARD INPUT ──────────────────────────────────────────────────
        if keyboard.is_pressed('s'):
            scroll_enabled = not scroll_enabled
            print(f"Scroll {'ON' if scroll_enabled else 'OFF'}")
            time.sleep(0.3)

        if keyboard.is_pressed('k'):
            toggle_osk()
            time.sleep(0.5)   # debounce

        if keyboard.is_pressed('q'):
            break

    cap.release()


if __name__ == "__main__":
    main()
