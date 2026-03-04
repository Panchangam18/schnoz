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
        drag_frozen_yaw = 0.0  # yaw/pitch frozen at drag start to avoid squint jitter
        drag_frozen_pitch = 0.0

        frame_count = 0
        _last_fps_time = time.time()
        _fps_frame_count = 0
        _last_loop_time = time.time()

        # Post-blink freeze: prevent cursor drift during double-blink inter-blink gap
        blink_freeze_until = 0.0
        was_blinking_prev = False

        try:
            while not self._stop_event.is_set():
                t_loop_start = time.time()
                loop_gap = t_loop_start - _last_loop_time
                _last_loop_time = t_loop_start

                ok, frame = cap.read()
                t_after_read = time.time()
                if not ok:
                    continue

                pose, is_blinking = extractor.extract_pose(frame)
                t_after_pose = time.time()
                frame_count += 1
                _fps_frame_count += 1

                # Periodic FPS + timing report (every 60 frames)
                if _fps_frame_count >= 60:
                    elapsed = time.time() - _last_fps_time
                    fps = _fps_frame_count / elapsed if elapsed > 0 else 0
                    print(f"[schnoz-debug] FPS={fps:.1f} (last {_fps_frame_count} frames in {elapsed:.2f}s)")
                    _fps_frame_count = 0
                    _last_fps_time = time.time()

                # Per-frame timing (every 30 frames to avoid spam)
                if frame_count % 30 == 0:
                    read_ms = (t_after_read - t_loop_start) * 1000
                    pose_ms = (t_after_pose - t_after_read) * 1000
                    gap_ms = loop_gap * 1000
                    cur_x, cur_y = cursor_ctl.last_x, cursor_ctl.last_y
                    print(f"[schnoz-debug] frame {frame_count}: loop_gap={gap_ms:.1f}ms cam_read={read_ms:.1f}ms pose={pose_ms:.1f}ms drag={drag_state} cursor=({cur_x:.0f},{cur_y:.0f})")

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
                        blink_freeze_until = 0.0
                        cursor_ctl.click()
                        did_click = True

                    # --- Drag state machine ---
                    elif drag_state == _DRAG_IDLE:
                        if pose.squinting:
                            drag_state = _DRAG_PENDING
                            squint_start_time = time.time()
                            extractor.freeze_baseline()
                            print(f"[schnoz-debug] DRAG IDLE→PENDING (squint detected, EAR={extractor._last_ear:.3f} baseline={extractor._open_baseline:.3f})")

                    elif drag_state == _DRAG_PENDING:
                        if not pose.squinting:
                            held = time.time() - squint_start_time
                            drag_state = _DRAG_IDLE
                            extractor.unfreeze_baseline()
                            print(f"[schnoz-debug] DRAG PENDING→IDLE (squint released after {held:.2f}s)")
                        elif time.time() - squint_start_time >= SQUINT_SUSTAIN_TIME:
                            drag_frozen_yaw = pose.yaw
                            drag_frozen_pitch = pose.pitch
                            cx, cy = projector.project(
                                pose.raw_nose_x, pose.raw_nose_y,
                                drag_frozen_yaw, drag_frozen_pitch,
                            )
                            drag_ema_x = cx
                            drag_ema_y = cy
                            cursor_ctl.mouse_down()
                            drag_state = _DRAG_ACTIVE
                            drag_start_time = time.time()
                            squint_release_time = None
                            double_take.reset()
                            print(f"[schnoz] DRAG START at ({drag_ema_x:.0f},{drag_ema_y:.0f})")

                    elif drag_state == _DRAG_ACTIVE:
                        eyes_relaxed = not pose.squinting and not is_blinking
                        if eyes_relaxed:
                            if squint_release_time is None:
                                squint_release_time = time.time()
                                print(f"[schnoz-debug] DRAG ACTIVE: eyes relaxed, starting release debounce")
                            elif time.time() - squint_release_time >= SQUINT_RELEASE_DEBOUNCE:
                                drag_dur = time.time() - drag_start_time
                                smoother.snap_to(int(drag_ema_x), int(drag_ema_y))
                                cursor_ctl.mouse_up()
                                drag_state = _DRAG_IDLE
                                extractor.unfreeze_baseline()
                                squint_release_time = None
                                print(f"[schnoz] DRAG END (duration={drag_dur:.2f}s)")
                        else:
                            squint_release_time = None

                    # --- Double-take detection (only when not dragging) ---
                    if drag_state == _DRAG_IDLE:
                        swipe_dir = double_take.update(pose.yaw)
                        if swipe_dir is not None:
                            keyboard_ctl.switch_space(swipe_dir)
                            print(f"[schnoz] SWIPE {swipe_dir.upper()} (double-take)")

                # --- Cursor movement ---
                # During active drag, always move (squinting keeps eyes half-closed
                # which registers as "blinking" — ignore that).
                # Otherwise freeze cursor during blinks, double-take, and post-blink
                # grace period (prevents drift during double-blink inter-blink gap).
                drag_active = drag_state == _DRAG_ACTIVE

                now_freeze = time.time()
                if was_blinking_prev and not is_blinking:
                    blink_freeze_until = now_freeze + 0.4
                was_blinking_prev = is_blinking

                cursor_frozen = now_freeze < blink_freeze_until
                can_move = pose is not None and not did_click and (drag_active or not double_take.mid_gesture)
                should_move = can_move and (drag_active or (not is_blinking and not cursor_frozen))
                if not should_move and frame_count % 30 == 0:
                    print(f"[schnoz-debug] frame {frame_count}: SKIPPED MOVE pose={pose is not None} click={did_click} mid_gesture={double_take.mid_gesture} drag_active={drag_active} blink={is_blinking} frozen={cursor_frozen}")
                if should_move:
                    t_proj_start = time.time()
                    if drag_active:
                        # During drag, use frozen yaw/pitch from drag start
                        # to eliminate squint-induced angular jitter.
                        cx, cy = projector.project(
                            pose.raw_nose_x, pose.raw_nose_y,
                            drag_frozen_yaw, drag_frozen_pitch,
                        )
                    else:
                        cx, cy = projector.project(
                            pose.raw_nose_x, pose.raw_nose_y,
                            pose.yaw, pose.pitch,
                        )
                    if drag_active:
                        # During drag, bypass smoother for responsive movement.
                        # Use light EMA (low alpha = less smoothing = more responsive).
                        drag_alpha = 0.15
                        old_ema_x, old_ema_y = drag_ema_x, drag_ema_y
                        drag_ema_x = drag_alpha * drag_ema_x + (1.0 - drag_alpha) * cx
                        drag_ema_y = drag_alpha * drag_ema_y + (1.0 - drag_alpha) * cy
                        sx, sy = int(drag_ema_x), int(drag_ema_y)
                        if frame_count % 10 == 0:
                            print(f"[schnoz-debug] frame {frame_count}: DRAG EMA old=({old_ema_x:.0f},{old_ema_y:.0f}) proj=({cx:.0f},{cy:.0f}) new=({drag_ema_x:.0f},{drag_ema_y:.0f}) final=({sx},{sy})")
                    else:
                        sx, sy = smoother.step(int(cx), int(cy))
                    if frame_count <= 5:
                        print(f"  projected=({cx:.0f},{cy:.0f}) smoothed=({sx},{sy})")
                    # Report BEFORE moving so the monitor never sees a stale expected pos
                    if self._mouse_monitor is not None:
                        self._mouse_monitor.report_programmatic_move(float(sx), float(sy))
                    cursor_ctl.move(sx, sy)
                    t_move_done = time.time()

                    # Periodic mouse movement timing (every 30 frames)
                    if frame_count % 30 == 0:
                        proj_ms = (t_move_done - t_proj_start) * 1000
                        total_ms = (t_move_done - t_loop_start) * 1000
                        mode = "DRAG" if drag_active else "NORMAL"
                        print(f"[schnoz-debug] frame {frame_count}: {mode} move→({sx},{sy}) proj+move={proj_ms:.1f}ms total_frame={total_ms:.1f}ms")

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
