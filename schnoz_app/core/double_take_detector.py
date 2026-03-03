"""DoubleTakeDetector: detects double-take head turn pattern from yaw values.

Pattern: turn head in a direction, return toward center, turn again in the
same direction. Returns 'left' or 'right' when detected.
"""

from __future__ import annotations

import time
from enum import Enum

from schnoz_app.config import (
    DOUBLE_TAKE_COOLDOWN,
    DOUBLE_TAKE_RETURN_THRESHOLD,
    DOUBLE_TAKE_TIME_WINDOW,
    DOUBLE_TAKE_TURN_THRESHOLD,
)


class _State(Enum):
    IDLE = "idle"
    FIRST_TURN = "first_turn"
    RETURNED = "returned"
    COOLDOWN = "cooldown"


class DoubleTakeDetector:
    """
    Detects a double-take head turn: turn in a direction, return toward
    center, turn in the same direction again.

    Feed yaw values via update() each frame. Returns 'left', 'right',
    or None.
    """

    def __init__(
        self,
        turn_threshold: float = DOUBLE_TAKE_TURN_THRESHOLD,
        return_threshold: float = DOUBLE_TAKE_RETURN_THRESHOLD,
        time_window: float = DOUBLE_TAKE_TIME_WINDOW,
        cooldown: float = DOUBLE_TAKE_COOLDOWN,
    ):
        self._turn_thresh = turn_threshold
        self._return_thresh = return_threshold
        self._time_window = time_window
        self._cooldown = cooldown

        self._state = _State.IDLE
        self._direction: str | None = None
        self._first_turn_time: float = 0.0
        self._cooldown_start: float = 0.0

    @property
    def mid_gesture(self) -> bool:
        """True if currently tracking a potential double-take."""
        return self._state in (_State.FIRST_TURN, _State.RETURNED)

    def update(self, yaw: float) -> str | None:
        """
        Feed a yaw value (radians). Returns 'left', 'right', or None.

        Positive yaw = head turned left, negative yaw = head turned right.
        """
        now = time.time()

        if self._state == _State.COOLDOWN:
            if now - self._cooldown_start >= self._cooldown:
                self._state = _State.IDLE
            return None

        if self._state == _State.IDLE:
            if yaw > self._turn_thresh:
                self._state = _State.FIRST_TURN
                self._direction = "left"
                self._first_turn_time = now
            elif yaw < -self._turn_thresh:
                self._state = _State.FIRST_TURN
                self._direction = "right"
                self._first_turn_time = now
            return None

        # Timeout for FIRST_TURN and RETURNED
        if now - self._first_turn_time > self._time_window:
            self._state = _State.IDLE
            self._direction = None
            return None

        if self._state == _State.FIRST_TURN:
            if abs(yaw) < self._return_thresh:
                self._state = _State.RETURNED
            return None

        if self._state == _State.RETURNED:
            if self._direction == "left" and yaw > self._turn_thresh:
                self._state = _State.COOLDOWN
                self._cooldown_start = now
                return "left"
            elif self._direction == "right" and yaw < -self._turn_thresh:
                self._state = _State.COOLDOWN
                self._cooldown_start = now
                return "right"
            return None

        return None
