"""Constants and configuration for Schnoz desktop app."""

import sys
from pathlib import Path

APP_NAME = "Schnoz"

# When bundled by PyInstaller, resources are in sys._MEIPASS
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    BUNDLE_DIR = Path(__file__).parent.parent

ASSETS_DIR = BUNDLE_DIR / "assets"
ICON_PATH = str(ASSETS_DIR / "schnoz_iconTemplate.png")

# Tracking defaults
DEFAULT_SENSITIVITY = 1.5
DEFAULT_POSITION_SCALE = 2.0
DEFAULT_EMA_ALPHA = 0.4
DEFAULT_PROCESS_VAR = 15.0
DEFAULT_CAMERA_INDEX = 0

# Squint detection (drag and drop)
DEFAULT_SQUINT_THRESHOLD_RATIO = 0.90
SQUINT_SUSTAIN_TIME = 0.40          # hold squint 400ms before drag activates (filters blinks)
SQUINT_RELEASE_DEBOUNCE = 0.25      # eyes open 250ms to end drag

# Double-take detection (space switching)
DOUBLE_TAKE_TURN_THRESHOLD = 0.06
DOUBLE_TAKE_RETURN_THRESHOLD = 0.03
DOUBLE_TAKE_TIME_WINDOW = 1.2
DOUBLE_TAKE_COOLDOWN = 1.5

# Wispr Flow
WISPRFLOW_API_KEY = "fl-48c6565f94a869138d5d81b9d672d834"
