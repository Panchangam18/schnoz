"""Schnoz: macOS menu bar app for hands-free cursor control.

Entry point: `python -m schnoz_app.app`

State machine:
  IDLE ──Cmd+Enter──────────> REGULAR ──Cmd+Enter or mouse──> IDLE
  IDLE ──Cmd+Shift+Enter────> ULTRA   ──Cmd+Shift+Enter or mouse──> IDLE
  REGULAR ──Cmd+Shift+Enter─> ULTRA   (upgrade: start voice)
  ULTRA ──Cmd+Enter─────────> REGULAR (downgrade: stop voice)
"""

from __future__ import annotations

import asyncio
import threading

import rumps

from schnoz_app.config import APP_NAME, ICON_PATH, WISPRFLOW_API_KEY
from schnoz_app.hotkey_listener import HotkeyListener
from schnoz_app.mouse_monitor import MouseMonitor
from schnoz_app.tracking_engine import TrackingEngine
from schnoz_app.wispr_engine import start_wispr_thread

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
IDLE = "idle"
REGULAR = "regular"
ULTRA = "ultra"


def _dispatch_to_main(fn):
    """Schedule a no-arg function to run on the main (rumps) thread."""
    def _fire(timer):
        timer.stop()
        fn()
    t = rumps.Timer(_fire, 0.01)
    t.start()


class SchnozApp(rumps.App):

    def __init__(self):
        super().__init__(APP_NAME, icon=ICON_PATH, title=None, quit_button=None)

        self._state = IDLE
        self._tracker: TrackingEngine | None = None
        self._wispr_thread: threading.Thread | None = None
        self._wispr_text_queue = None
        self._wispr_loop: asyncio.AbstractEventLoop | None = None
        self._wispr_client = None

        # Menu items
        self._regular_item = rumps.MenuItem("Regular Mode  ⌘↩", callback=self._menu_regular)
        self._ultra_item = rumps.MenuItem("Ultra Schnoz  ⌘⇧↩", callback=self._menu_ultra)
        self._quit_item = rumps.MenuItem("Quit Schnoz", callback=self._quit)

        self.menu = [
            self._regular_item,
            self._ultra_item,
            None,  # separator
            self._quit_item,
        ]

        # Mouse monitor (detects physical mouse movement)
        self._mouse_monitor = MouseMonitor(on_external_move=self._on_external_mouse)

        # Hotkey listener
        self._hotkeys = HotkeyListener(
            on_regular=self._on_hotkey_regular,
            on_ultra=self._on_hotkey_ultra,
        )

    # -- Lifecycle ----------------------------------------------------------

    def _post_init(self, timer):
        """Called once after rumps app starts running."""
        timer.stop()
        self._mouse_monitor.start()
        self._hotkeys.start()
        print(f"[schnoz] {APP_NAME} is running")
        print("[schnoz] Cmd+Enter = Regular Mode, Cmd+Shift+Enter = Ultra Schnoz")

    # -- Hotkey callbacks (called from pynput thread) -----------------------

    def _on_hotkey_regular(self):
        """Dispatch to main thread."""
        _dispatch_to_main(self.toggle_regular)

    def _on_hotkey_ultra(self):
        """Dispatch to main thread."""
        _dispatch_to_main(self.toggle_ultra)

    # -- Menu callbacks (called from main thread) ---------------------------

    def _menu_regular(self, sender):
        self.toggle_regular()

    def _menu_ultra(self, sender):
        self.toggle_ultra()

    def _quit(self, sender):
        self._stop_all()
        self._hotkeys.stop()
        rumps.quit_application()

    # -- State transitions --------------------------------------------------

    def toggle_regular(self):
        if self._state == IDLE:
            self._start_tracking()
            self._state = REGULAR
        elif self._state == REGULAR:
            self._stop_all()
        elif self._state == ULTRA:
            self._stop_wispr()
            self._state = REGULAR
        self._update_ui()

    def toggle_ultra(self):
        if self._state == IDLE:
            self._start_tracking()
            self._start_wispr()
            self._state = ULTRA
        elif self._state == ULTRA:
            self._stop_all()
        elif self._state == REGULAR:
            self._start_wispr()
            self._state = ULTRA
        self._update_ui()

    def _on_external_mouse(self):
        """Called from mouse monitor thread when physical mouse is detected."""
        _dispatch_to_main(self._handle_external_mouse)

    def _handle_external_mouse(self):
        """Handle external mouse on main thread."""
        if self._state != IDLE:
            print("[schnoz] Physical mouse detected — stopping tracking")
            self._stop_all()
            self._update_ui()

    # -- Start/stop helpers -------------------------------------------------

    def _start_tracking(self):
        if self._tracker is None or not self._tracker.running:
            self._tracker = TrackingEngine(mouse_monitor=self._mouse_monitor)
            self._tracker.start()
            self._mouse_monitor.enable()
            print(f"[schnoz] Tracking started")

    def _start_wispr(self):
        if self._wispr_thread is None:
            thread, text_queue, loop, client = start_wispr_thread(WISPRFLOW_API_KEY)
            self._wispr_thread = thread
            self._wispr_text_queue = text_queue
            self._wispr_loop = loop
            self._wispr_client = client
            # Connect the text queue to the tracker
            if self._tracker is not None:
                self._tracker.set_text_queue(text_queue)
            print("[schnoz] Voice typing started (always listening)")

    def _stop_wispr(self):
        if self._wispr_client is not None:
            # Schedule shutdown on the wispr event loop
            asyncio.run_coroutine_threadsafe(
                self._wispr_client.shutdown(), self._wispr_loop,
            )
        if self._tracker is not None:
            self._tracker.set_text_queue(None)
        self._wispr_thread = None
        self._wispr_text_queue = None
        self._wispr_loop = None
        self._wispr_client = None
        print("[schnoz] Voice typing stopped")

    def _stop_tracking(self):
        self._mouse_monitor.disable()
        if self._tracker is not None:
            self._tracker.stop()
            self._tracker = None
            print("[schnoz] Tracking stopped")

    def _stop_all(self):
        self._stop_wispr()
        self._stop_tracking()
        self._state = IDLE

    # -- UI updates ---------------------------------------------------------

    def _update_ui(self):
        self._regular_item.state = self._state in (REGULAR, ULTRA)
        self._ultra_item.state = self._state == ULTRA

        # Small text next to icon to indicate active mode
        if self._state == IDLE:
            self.title = None
        elif self._state == REGULAR:
            self.title = "ON"
        elif self._state == ULTRA:
            self.title = "ULTRA"


def main():
    app = SchnozApp()
    # One-shot timer to run post-init after the run loop starts
    t = rumps.Timer(app._post_init, 0.5)
    t.start()
    app.run()


if __name__ == "__main__":
    main()
