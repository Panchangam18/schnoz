# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Schnoz macOS menu bar app."""

import os
import sys

block_cipher = None

# Find package locations
import mediapipe
import cv2

mediapipe_dir = os.path.dirname(mediapipe.__file__)
cv2_dir = os.path.dirname(cv2.__file__)

# Collect mediapipe data files (models, configs)
mediapipe_datas = []
for root, dirs, files in os.walk(mediapipe_dir):
    for f in files:
        if f.endswith(('.tflite', '.binarypb', '.txt', '.pbtxt', '.task')):
            src = os.path.join(root, f)
            dst = os.path.relpath(root, os.path.dirname(mediapipe_dir))
            mediapipe_datas.append((src, dst))

a = Analysis(
    ['schnoz_app/app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/schnoz_iconTemplate.png', 'assets'),
        ('assets/Copy of schnoz-logo-2.png', 'assets'),
    ] + mediapipe_datas,
    hiddenimports=[
        'rumps',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput.mouse',
        'pynput.mouse._darwin',
        'mediapipe',
        'mediapipe.tasks',
        'mediapipe.tasks.python',
        'mediapipe.tasks.python.vision',
        'mediapipe.tasks.python.core',
        'mediapipe.tasks.python.core.base_options',
        'cv2',
        'numpy',
        'sounddevice',
        '_sounddevice_data',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'schnoz_app',
        'schnoz_app.config',
        'schnoz_app.app',
        'schnoz_app.tracking_engine',
        'schnoz_app.mouse_monitor',
        'schnoz_app.wispr_engine',
        'schnoz_app.hotkey_listener',
        'schnoz_app.platform',
        'schnoz_app.platform.cursor_mac',
        'schnoz_app.platform.keyboard_mac',
        'schnoz_app.platform.screen_mac',
        'schnoz_app.core',
        'schnoz_app.core.feature_extractor',
        'schnoz_app.core.projection',
        'schnoz_app.core.smoother',
        'Quartz',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Schnoz',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Schnoz',
)

app = BUNDLE(
    coll,
    name='Schnoz.app',
    icon='assets/Schnoz.icns',
    bundle_identifier='com.schnoz.app',
    info_plist={
        'LSUIElement': True,
        'CFBundleName': 'Schnoz',
        'CFBundleDisplayName': 'Schnoz',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSCameraUsageDescription': 'Schnoz needs camera access for head tracking.',
        'NSMicrophoneUsageDescription': 'Schnoz needs microphone access for voice typing.',
        'NSAppleEventsUsageDescription': 'Schnoz needs accessibility access for cursor control.',
        'NSHighResolutionCapable': True,
    },
)
