"""Helpers for macOS Accessibility Shortcut based Head Pointer control."""

from __future__ import annotations

import subprocess
import time


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def is_head_pointer_enabled() -> bool:
    """Return current macOS Head Pointer state."""
    result = _run(["defaults", "read", "com.apple.universalaccess", "headMouseEnabled"])
    if result.returncode != 0:
        return False
    return (result.stdout or "").strip() == "1"


def trigger_accessibility_shortcut() -> bool:
    """Press Option+Command+F5 via System Events."""
    script = 'tell application "System Events" to key code 96 using {command down, option down}'
    result = _run(["osascript", "-e", script])
    return result.returncode == 0


def set_head_pointer_enabled(enabled: bool) -> bool:
    """
    Ensure Head Pointer is on/off.

    Note: this relies on Accessibility Shortcut being configured with only Head Pointer.
    """
    current = is_head_pointer_enabled()
    if current == enabled:
        return True
    if not trigger_accessibility_shortcut():
        return False
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if is_head_pointer_enabled() == enabled:
            return True
        time.sleep(0.1)
    return False
