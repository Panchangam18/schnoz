"""py2app setup for Schnoz desktop app."""

from setuptools import setup

APP = ["schnoz_app/app.py"]
DATA_FILES = [("assets", ["assets/schnoz_icon.png", "assets/schnoz_icon_active.png"])]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,  # No dock icon
        "CFBundleName": "Schnoz",
        "CFBundleDisplayName": "Schnoz",
        "CFBundleIdentifier": "com.schnoz.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSCameraUsageDescription": "Schnoz needs camera access for head tracking.",
        "NSMicrophoneUsageDescription": "Schnoz needs microphone access for voice typing.",
    },
    "packages": [
        "rumps",
        "mediapipe",
        "cv2",
        "numpy",
        "sounddevice",
        "websockets",
        "pynput",
        "schnoz_app",
    ],
}

setup(
    name="Schnoz",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
