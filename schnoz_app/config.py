"""Constants and configuration for Schnoz desktop app."""

from pathlib import Path

APP_NAME = "Schnoz"
BUNDLE_DIR = Path(__file__).parent.parent
ASSETS_DIR = BUNDLE_DIR / "assets"
ICON_PATH = str(ASSETS_DIR / "schnoz_icon.png")
ICON_ACTIVE_PATH = str(ASSETS_DIR / "schnoz_icon_active.png")

# Tracking defaults
DEFAULT_SENSITIVITY = 1.5
DEFAULT_POSITION_SCALE = 2.0
DEFAULT_EMA_ALPHA = 0.4
DEFAULT_PROCESS_VAR = 15.0
DEFAULT_CAMERA_INDEX = 0

# Wispr Flow
WISPRFLOW_API_KEY = "fl-48c6565f94a869138d5d81b9d672d834"
