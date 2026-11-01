#!/usr/bin/env bash
# 建 Apple Silicon 版 .app 與 .dmg（不含模型、不含任何會議資料）。
# dmg 檔名固定不帶版本號，官網可以永遠指向 releases/latest/download/EchoicLocal-mac-arm64.dmg。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_BIN="$ROOT/build/runtime/bin"
DIST="$ROOT/dist"
APP_NAME="Echoic 本機版"
VERSION="$("$ROOT/.venv/bin/python" -c 'import meeting_local; print(meeting_local.__version__)')"
export MEETING_LOCAL_PACKAGE_VERSION="$VERSION"

"$ROOT/scripts/build-macos-deps.sh"
uv pip install --python "$ROOT/.venv/bin/python" -e "$ROOT[package]"

export MEETING_LOCAL_PACKAGE_FFMPEG="$RUNTIME_BIN/ffmpeg"
export MEETING_LOCAL_PACKAGE_FFPROBE="$RUNTIME_BIN/ffprobe"
export MEETING_LOCAL_PACKAGE_WHISPER_SERVER="$RUNTIME_BIN/whisper-server"

"$ROOT/.venv/bin/python" -m PyInstaller --noconfirm --clean \
  --workpath "$ROOT/build/pyinstaller" \
  --distpath "$DIST" \
  "$ROOT/echoic-local.spec"

# ad-hoc 簽署：可驗證 bundle 完整性，但不是 Apple Developer ID 公證；第一次開啟要「右鍵 → 打開」。
codesign --force --deep --sign - "$DIST/${APP_NAME}.app"
codesign --verify --deep --strict --verbose=2 "$DIST/${APP_NAME}.app"

DMG="$DIST/EchoicLocal-mac-arm64.dmg"
rm -f "$DMG"
STAGE="$ROOT/build/dmg-stage"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$DIST/${APP_NAME}.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "${APP_NAME}" -srcfolder "$STAGE" -format UDZO "$DMG"
hdiutil verify "$DMG"
( cd "$DIST" && shasum -a 256 "$(basename "$DMG")" > SHA256SUMS.txt )
echo "✅ ${VERSION}：$DMG"
cat "$DIST/SHA256SUMS.txt"
