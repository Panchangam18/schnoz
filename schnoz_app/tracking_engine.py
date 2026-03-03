"""TrackingEngine: headless nose-tracking thread.

Runs the camera → MediaPipe → projection → smoother → cursor pipeline
in a background thread. No OpenCV windows — purely headless.
"""

from __future__ import annotations

import queue
import threading
import time

import cv2

from schnoz_app.config import (
    DEFAULT_CAMERA_INDEX,
    DEFAULT_EMA_ALPHA,
    DEFAULT_POSITION_SCALE,
    DEFAULT_PROCESS_VAR,
    DEFAULT_SENSITIVITY,
    SQUINT_RELEASE_DEBOUNCE,
    SQUINT_SUSTAIN_TIME,
)
from schnoz_app.core.double_take_detector import DoubleTakeDetector
from schnoz_app.core.feature_extractor import NoseFeatureExtractor
from schnoz_app.core.projection import NoseProjector
from schnoz_app.core.smoother import KalmanEMASmoother, make_kalman
from schnoz_app.platform import CursorController, KeyboardController, get_screen_size

# Drag state constants
_DRAG_IDLE = "idle"
_DRAG_PENDING = "pending"
_DRAG_ACTIVE = "active"


class TrackingEngine:
    """Stoppable nose-tracking thread."""

    def __init__(self, text_queue: queue.Queue | None = None, mouse_monitor=None):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._text_queue = text_queue
        self._mouse_monitor = mouse_monitor

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_text_queue(self, q: queue.Queue | None):
        """Set or clear the wispr text queue (for upgrading/downgrading modes)."""
        self._text_queue = q

    def start(self):
        """Start the tracking thread."""
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="tracking")
        self._thread.start()

    def stop(self):
        """Stop the tracking thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self):
        extractor = NoseFeatureExtractor()
        cursor_ctl = CursorController()
        keyboard_ctl = KeyboardController()
        screen_w, screen_h = get_screen_size()

        cap = cv2.VideoCapture(DEFAULT_CAMERA_INDEX)
        if not cap.isOpened():
            print("[schnoz] Failed to open camera")
            extractor.close()
            return

        cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        projector = NoseProjector(
            screen_w=screen_w,
            screen_h=screen_h,
            cam_w=cam_w,
            cam_h=cam_h,
            sensitivity=DEFAULT_SENSITIVITY,
            position_scale=DEFAULT_POSITION_SCALE,
        )
        kalman = make_kalman(process_var=DEFAULT_PROCESS_VAR)
        smoother = KalmanEMASmoother(kalman, ema_alpha=DEFAULT_EMA_ALPHA)
        double_take = DoubleTakeDetector()

        # Drag state
        drag_state = _DRAG_IDLE
        squint_start_time = 0.0
        squint_release_time: float | None = None
        drag_start_time = 0.0  # when drag activated (for grace period)
        drag_ema_x = 0.0  # lightweight EMA for responsive drag movement
        drag_ema_y = 0.0

        frame_count = 0
        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    continue

                pose, is_blinking = extractor.extract_pose(frame)
                frame_count += 1

                if frame_count <= 5:
                    print(f"[schnoz] frame {frame_count}: pose={pose is not None}, blinking={is_blinking}")
                    if pose is not None:
                        print(f"  nose=({pose.raw_nose_x:.0f},{pose.raw_nose_y:.0f}) yaw={pose.yaw:.3f} pitch={pose.pitch:.3f}")

                did_click = False

                if pose is not None:
                    # --- Double-blink click (works in any drag state) ---
                    if pose.double_blink:
                        if drag_state == _DRAG_ACTIVE:
                            cursor_ctl.mouse_up()
                        if drag_state != _DRAG_IDLE:
                            extractor.unfreeze_baseline()
                        drag_state = _DRAG_IDLE
                        squint_release_time = None
                        cursor_ctl.click()
                        did_click = True

                    # --- Drag state machine ---
                    elif drag_state == _DRAG_IDLE:
                        if pose.squinting:
                            drag_state = _DRAG_PENDING
                            squint_start_time = time.time()
                            extractor.freeze_baseline()

                    elif drag_state == _DRAG_PENDING:
                        if not pose.squinting:
                            drag_state = _DRAG_IDLE
                            extractor.unfreeze_baseline()
                        elif time.time() - squint_start_time >= SQUINT_SUSTAIN_TIME:
                            cx, cy = projector.project(
                                pose.raw_nose_x, pose.raw_nose_y,
                                pose.yaw, pose.pitch,
                            )
                            drag_ema_x = cx
                            drag_ema_y = cy
                            cursor_ctl.mouse_down()
                            drag_state = _DRAG_ACTIVE
                            drag_start_time = time.time()
                            squint_release_time = None
                            print("[schnoz] DRAG START")

                    elif drag_state == _DRAG_ACTIVE:
                        eyes_relaxed = not pose.squinting and not is_blinking
                        if eyes_relaxed:
                            if squint_release_time is None:
                                squint_release_time = time.time()
                            elif time.time() - squint_release_time >= SQUINT_RELEASE_DEBOUNCE:
                                smoother.snap_to(int(drag_ema_x), int(drag_ema_y))
                                cursor_ctl.mouse_up()
                                drag_state = _DRAG_IDLE
                                extractor.unfreeze_baseline()
                                squint_release_time = None
                                print("[schnoz] DRAG END")
                        else:
                            squint_release_time = None

                    # --- Double-take detection (only when not dragging) ---
                    if drag_state == _DRAG_IDLE:
                        swipe_dir = double_take.update(pose.yaw)
                        if swipe_dir is not None:
                            keyboard_ctl.switch_space(swipe_dir)
                            print(f"[schnoz] SWIPE {swipe_dir.upper()} (double-take)")

                # --- Cursor movement ---
                # Freeze cursor during pending squint and double-take gesture
                if pose is not None and not is_blinking and not did_click and not double_take.mid_gesture and drag_state != _DRAG_PENDING:
                    cx, cy = projector.project(
                        pose.raw_nose_x, pose.raw_nose_y,
                        pose.yaw, pose.pitch,
                    )
                    if drag_state == _DRAG_ACTIVE:
                        # During drag, bypass smoother for responsive movement.
                        # Use light EMA only (no Kalman) to reduce jitter.
                        drag_alpha = 0.3  # lower = more responsive
                        drag_ema_x = drag_alpha * drag_ema_x + (1.0 - drag_alpha) * cx
                        drag_ema_y = drag_alpha * drag_ema_y + (1.0 - drag_alpha) * cy
                        sx, sy = int(drag_ema_x), int(drag_ema_y)
                    else:
                        sx, sy = smoother.step(int(cx), int(cy))
                    if frame_count <= 5:
                        print(f"  projected=({cx:.0f},{cy:.0f}) smoothed=({sx},{sy})")
                    # Report BEFORE moving so the monitor never sees a stale expected pos
                    if self._mouse_monitor is not None:
                        self._mouse_monitor.report_programmatic_move(float(sx), float(sy))
                    cursor_ctl.move(sx, sy)

                # Poll for transcribed text from Wispr (Ultra mode)
                text_q = self._text_queue
                if text_q is not None:
                    while True:
                        try:
                            text = text_q.get_nowait()
                            keyboard_ctl.type_text(text)
                        except queue.Empty:
                            break
        finally:
            if drag_state == _DRAG_ACTIVE:
                cursor_ctl.mouse_up()
                print("[schnoz] DRAG cleanup (engine stopping)")
            cap.release()
            extractor.close()
