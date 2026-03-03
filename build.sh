#!/usr/bin/env bash
# Build Schnoz.app and create DMG for distribution.
# Usage: ./build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building Schnoz.app with PyInstaller..."
pyinstaller schnoz.spec --noconfirm

echo "==> Creating DMG..."
STAGING="/tmp/schnoz-dmg-staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R dist/Schnoz.app "$STAGING/"
ln -s /Applications "$STAGING/Applications"

rm -f dist/Schnoz.dmg
hdiutil create \
  -volname "Schnoz" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  dist/Schnoz.dmg

rm -rf "$STAGING"

echo "==> Done! dist/Schnoz.dmg ($(du -h dist/Schnoz.dmg | cut -f1))"
