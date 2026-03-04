"""MouseMonitor: detects when the user physically moves their mouse/trackpad.

Approach: polls the actual cursor position periodically. If the cursor position
deviates significantly from where the tracking engine last placed it, we know
the user moved their mouse manually. This is more reliable than CGEvent tap
PID checking, which doesn't work for CGEventPost from background threads.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from Quartz import CGEventCreate, CGEventGetLocation


def _get_cursor_pos() -> tuple[float, float]:
    """Get the current cursor position via Quartz."""
    event = CGEventCreate(None)
    loc = CGEventGetLocation(event)
    return loc.x, loc.y


# How far the cursor must deviate from expected position to count as "external"
_DEVIATION_THRESHOLD = 30.0

# How often to check (seconds)
_POLL_INTERVAL = 0.1


class MouseMonitor:
    """Detects physical mouse movement by polling cursor position."""

    def __init__(self, on_external_move: Callable[[], None]):
        self._callback = on_external_move
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Last position the tracking engine moved the cursor to
        self._lock = threading.Lock()
        self._expected_x: float = 0.0
        self._expected_y: float = 0.0
        self._has_expected: bool = False

    def start(self):
        """Start the monitor thread. Call once at app launch."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mouse-monitor")
        self._thread.start()

    def enable(self):
        """Enable monitoring (when tracking is active)."""
        with self._lock:
            self._has_expected = False
        self._enabled = True

    def disable(self):
        """Disable monitoring (when tracking is inactive)."""
        self._enabled = False
        with self._lock:
            self._has_expected = False

    def report_programmatic_move(self, x: float, y: float):
        """Called by the tracking engine after each cursor move."""
        with self._lock:
            self._expected_x = x
            self._expected_y = y
            self._has_expected = True

    def _run(self):
        _consecutive_deviations = 0
        _poll_count = 0
        while not self._stop_event.is_set():
            t_poll_start = time.time()
            time.sleep(_POLL_INTERVAL)

            if not self._enabled:
                _consecutive_deviations = 0
                continue

            with self._lock:
                if not self._has_expected:
                    _consecutive_deviations = 0
                    continue
                ex, ey = self._expected_x, self._expected_y

            ax, ay = _get_cursor_pos()
            t_poll_end = time.time()
            dx = abs(ax - ex)
            dy = abs(ay - ey)

            _poll_count += 1
            # Periodic poll timing (every 50 polls ~ every 5s)
            if _poll_count % 50 == 0:
                poll_ms = (t_poll_end - t_poll_start) * 1000
                print(f"[schnoz-debug] mouse_monitor poll #{_poll_count}: poll_time={poll_ms:.1f}ms actual=({ax:.0f},{ay:.0f}) expected=({ex:.0f},{ey:.0f}) delta=({dx:.0f},{dy:.0f})")

            if dx > _DEVIATION_THRESHOLD or dy > _DEVIATION_THRESHOLD:
                _consecutive_deviations += 1
                if _consecutive_deviations >= 2:
                    print(f"[mouse-monitor] EXTERNAL MOUSE DETECTED! delta=({dx:.0f},{dy:.0f})")
                    self._enabled = False
                    self._callback()
            else:
                _consecutive_deviations = 0
