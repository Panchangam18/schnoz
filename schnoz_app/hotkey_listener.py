"""HotkeyListener: global keyboard shortcuts via pynput.

Registers Cmd+Enter (regular mode) and Cmd+Shift+Enter (ultra schnoz).
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
        self._hotkeys: keyboard.GlobalHotKeys | None = None

    def start(self):
        """Start listening for global hotkeys. Non-blocking (runs in background thread)."""
        self._hotkeys = keyboard.GlobalHotKeys({
            "<cmd>+<enter>": self._on_regular,
            "<cmd>+<shift>+<enter>": self._on_ultra,
        })
        self._hotkeys.daemon = True
        self._hotkeys.start()

    def stop(self):
        """Stop listening."""
        if self._hotkeys is not None:
            self._hotkeys.stop()
            self._hotkeys = None
