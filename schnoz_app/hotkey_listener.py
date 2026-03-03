"""HotkeyListener: global keyboard shortcuts via pynput.

Registers Cmd+Enter (regular mode) and Cmd+Shift+Enter (ultra schnoz).

Uses a manual keyboard.Listener instead of GlobalHotKeys to work around
a pynput 1.8.x bug on macOS where GlobalHotKeys._on_press() receives an
unexpected `injected` argument from the Darwin backend.
"""

from __future__ import annotations

from typing import Callable

from pynput import keyboard


class HotkeyListener:
    """Listens for global hotkeys and dispatches callbacks."""

    def __init__(
        self,
        on_regular: Callable[[], None],
        on_ultra: Callable[[], None],
    ):
        self._on_regular = on_regular
        self._on_ultra = on_ultra
        self._listener: keyboard.Listener | None = None
        self._pressed: set = set()

    def _on_press(self, key):
        self._pressed.add(key)
        if key == keyboard.Key.enter:
            cmd = (
                keyboard.Key.cmd in self._pressed
                or keyboard.Key.cmd_l in self._pressed
                or keyboard.Key.cmd_r in self._pressed
            )
            shift = (
                keyboard.Key.shift in self._pressed
                or keyboard.Key.shift_l in self._pressed
                or keyboard.Key.shift_r in self._pressed
            )
            if cmd and shift:
                self._on_ultra()
            elif cmd:
                self._on_regular()

    def _on_release(self, key):
        self._pressed.discard(key)

    def start(self):
        """Start listening for global hotkeys. Non-blocking (runs in background thread)."""
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        """Stop listening."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
