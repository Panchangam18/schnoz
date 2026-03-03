"""TrackingEngine: headless nose-tracking thread.

Runs the camera → MediaPipe → projection → smoother → cursor pipeline
in a background thread. No OpenCV windows — purely headless.
"""

from __future__ import annotations

import queue
import threading

import cv2

from schnoz_app.config import (
    DEFAULT_CAMERA_INDEX,
    DEFAULT_EMA_ALPHA,
    DEFAULT_POSITION_SCALE,
    DEFAULT_PROCESS_VAR,
    DEFAULT_SENSITIVITY,
)
from schnoz_app.core.feature_extractor import NoseFeatureExtractor
from schnoz_app.core.projection import NoseProjector
from schnoz_app.core.smoother import KalmanEMASmoother, make_kalman
from schnoz_app.platform import CursorController, KeyboardController, get_screen_size


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

                # Double-blink → click
                did_click = False
                if pose is not None and pose.double_blink:
                    cursor_ctl.click()
                    did_click = True

                # Head tracking → cursor movement
                if pose is not None and not is_blinking and not did_click:
                    cx, cy = projector.project(
                        pose.raw_nose_x, pose.raw_nose_y,
                        pose.yaw, pose.pitch,
                    )
                    sx, sy = smoother.step(int(cx), int(cy))
                    if frame_count <= 5:
                        print(f"  projected=({cx:.0f},{cy:.0f}) smoothed=({sx},{sy})")
                    cursor_ctl.move(sx, sy)
                    # Report to mouse monitor so it doesn't treat our move as external
                    if self._mouse_monitor is not None:
                        self._mouse_monitor.report_programmatic_move(float(sx), float(sy))

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
            cap.release()
            extractor.close()
