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
DEFAULT_SENSITIVITY = 1.0
DEFAULT_VERTICAL_SENSITIVITY = 2.5
DEFAULT_ACCEL_EXPONENT = 2.0  # >1 = slow moves slower, fast moves faster
DEFAULT_POSITION_SCALE = 2.0
DEFAULT_HORIZONTAL_POSITION_SCALE = 0.5
DEFAULT_EMA_ALPHA = 0.70
DEFAULT_PROCESS_VAR = 1.2
DEFAULT_CAMERA_INDEX = 0

# Squint detection (drag and drop)
DEFAULT_SQUINT_THRESHOLD_RATIO = 0.85
SQUINT_SUSTAIN_TIME = 0.5           # hold squint 0.5s before drag activates (filters blinks)
SQUINT_RELEASE_DEBOUNCE = 0.0       # eyes open = immediate drag end

# Wispr Flow
WISPRFLOW_API_KEY = "fl-48c6565f94a869138d5d81b9d672d834"
