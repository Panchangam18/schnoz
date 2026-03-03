"""Screen utilities for macOS via Quartz."""

from Quartz import CGDisplayBounds, CGMainDisplayID


def get_screen_size() -> tuple[int, int]:
    bounds = CGDisplayBounds(CGMainDisplayID())
    return int(bounds.size.width), int(bounds.size.height)
