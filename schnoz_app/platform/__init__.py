"""Platform abstraction — imports the correct backend for the current OS."""

import sys

if sys.platform == "darwin":
    from schnoz_app.platform.cursor_mac import CursorController
    from schnoz_app.platform.keyboard_mac import KeyboardController
    from schnoz_app.platform.screen_mac import get_screen_size
else:
    raise NotImplementedError(f"Platform {sys.platform!r} not yet supported")
