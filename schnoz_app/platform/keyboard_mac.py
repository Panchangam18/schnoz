"""KeyboardController: injects text as keyboard events via Quartz CoreGraphics."""

from __future__ import annotations

from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    kCGHIDEventTap,
)

MAX_UNICODE_PER_EVENT = 20  # macOS limit per CGEvent


class KeyboardController:
    """Injects Unicode text into macOS as synthetic keyboard events."""

    def type_text(self, text: str):
        for i in range(0, len(text), MAX_UNICODE_PER_EVENT):
            chunk = text[i : i + MAX_UNICODE_PER_EVENT]
            down = CGEventCreateKeyboardEvent(None, 0, True)
            CGEventKeyboardSetUnicodeString(down, len(chunk), chunk)
            CGEventPost(kCGHIDEventTap, down)
            up = CGEventCreateKeyboardEvent(None, 0, False)
            CGEventPost(kCGHIDEventTap, up)
