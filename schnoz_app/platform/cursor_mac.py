"""CursorController: moves the macOS cursor via Quartz CoreGraphics."""

from __future__ import annotations

import time

import numpy as np
from AppKit import NSCursor
from Quartz import (
    CGDisplayBounds,
    CGEventCreateMouseEvent,
    CGEventPost,
    CGMainDisplayID,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseDragged,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGEventRightMouseDown,
    kCGEventRightMouseUp,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
    kCGMouseButtonRight,
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
        self._move_count = 0
        self._drag_move_count = 0

    def move(self, x, y):
        if self._dragging:
            return self.drag_move(x, y)

        x = float(np.clip(x, 0, self.screen_w))
        y = float(np.clip(y, 0, self.screen_h))

        if abs(x - self.last_x) < DEAD_ZONE_PX and abs(y - self.last_y) < DEAD_ZONE_PX:
            return

        self.last_x = x
        self.last_y = y

        t0 = time.time()
        event = CGEventCreateMouseEvent(
            None, kCGEventMouseMoved, (x, y), kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, event)
        self._move_count += 1
        if self._move_count % 30 == 0:
            cg_ms = (time.time() - t0) * 1000
            print(f"[schnoz-debug] cursor move #{self._move_count}: CGEventPost={cg_ms:.2f}ms pos=({x:.0f},{y:.0f})")

    def mouse_down(self):
        pos = (self.last_x, self.last_y)
        down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, down)
        self._dragging = True
        NSCursor.closedHandCursor().set()

    def mouse_up(self):
        pos = (self.last_x, self.last_y)
        up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, pos, kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, up)
        self._dragging = False
        NSCursor.arrowCursor().set()

    def drag_move(self, x, y):
        x = float(np.clip(x, 0, self.screen_w))
        y = float(np.clip(y, 0, self.screen_h))

        self.last_x = x
        self.last_y = y

        t0 = time.time()
        event = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDragged, (x, y), kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, event)
        self._drag_move_count += 1
        if self._drag_move_count % 10 == 0:
            cg_ms = (time.time() - t0) * 1000
            print(f"[schnoz-debug] drag_move #{self._drag_move_count}: CGEventPost={cg_ms:.2f}ms pos=({x:.0f},{y:.0f})")

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

    def right_click(self):
        pos = (self.last_x, self.last_y)
        down = CGEventCreateMouseEvent(
            None, kCGEventRightMouseDown, pos, kCGMouseButtonRight,
        )
        CGEventPost(kCGHIDEventTap, down)
        up = CGEventCreateMouseEvent(
            None, kCGEventRightMouseUp, pos, kCGMouseButtonRight,
        )
        CGEventPost(kCGHIDEventTap, up)
