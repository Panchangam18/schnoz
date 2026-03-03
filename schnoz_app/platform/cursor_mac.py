"""CursorController: moves the macOS cursor via Quartz CoreGraphics."""

from __future__ import annotations

import numpy as np
from Quartz import (
    CGDisplayBounds,
    CGEventCreateMouseEvent,
    CGEventPost,
    CGMainDisplayID,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseDragged,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
)

DEAD_ZONE_PX = 3


class CursorController:

    def __init__(self):
        bounds = CGDisplayBounds(CGMainDisplayID())
        self.screen_w = int(bounds.size.width)
        self.screen_h = int(bounds.size.height)
        self.last_x = self.screen_w / 2.0
        self.last_y = self.screen_h / 2.0
        self._dragging = False

    def move(self, x, y):
        if self._dragging:
            return self.drag_move(x, y)

        x = float(np.clip(x, 0, self.screen_w))
        y = float(np.clip(y, 0, self.screen_h))

        if abs(x - self.last_x) < DEAD_ZONE_PX and abs(y - self.last_y) < DEAD_ZONE_PX:
            return

        self.last_x = x
        self.last_y = y

        event = CGEventCreateMouseEvent(
            None, kCGEventMouseMoved, (x, y), kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, event)

    def mouse_down(self):
        pos = (self.last_x, self.last_y)
        down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, down)
        self._dragging = True

    def mouse_up(self):
        pos = (self.last_x, self.last_y)
        up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, up)
        self._dragging = False

    def drag_move(self, x, y):
        x = float(np.clip(x, 0, self.screen_w))
        y = float(np.clip(y, 0, self.screen_h))

        if abs(x - self.last_x) < DEAD_ZONE_PX and abs(y - self.last_y) < DEAD_ZONE_PX:
            return

        self.last_x = x
        self.last_y = y

        event = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDragged, (x, y), kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, event)

    def click(self):
        pos = (self.last_x, self.last_y)
        down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, down)
        up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, up)
