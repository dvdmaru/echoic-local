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

# ad-hoc 簽署：可驗證 bundle 完整性，但不是 Apple Developer ID 公證；第一次開啟要到「系統設定 → 隱私權與安全性」按「仍要打開」（macOS 15 起右鍵 → 打開已無效）。
codesign --force --deep --sign - "$DIST/${APP_NAME}.app"
codesign --verify --deep --strict --verbose=2 "$DIST/${APP_NAME}.app"

# 冒煙測試：模擬 Finder 啟動（沒有 LANG／LC_*）。視窗起得來＝8 秒內不會自己結束。
# 2026-11-03 由來：0.3.0 只從終端機（有 LANG）測過，Finder 一開就因 Tcl 讀壞中文路徑而結束。
SMOKE_LOG="$ROOT/build/smoke-finder-env.log"
env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="${TMPDIR:-/tmp}" \
  "$DIST/${APP_NAME}.app/Contents/MacOS/${APP_NAME}" >"$SMOKE_LOG" 2>&1 </dev/null &
SMOKE_PID=$!
sleep 8
if kill -0 "$SMOKE_PID" 2>/dev/null; then
  # 收掉測試用的 App：TERM 後最多等 10 秒，還在就 KILL。不能直接 wait——
  # 2026-11-10 背景跑三次卡兩次（TERM 沒生效、wait 無限等 2 小時，沒有任何錯誤訊息）；手動補一次 TERM 就結束。
  kill "$SMOKE_PID" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$SMOKE_PID" 2>/dev/null || break
    sleep 1
    kill "$SMOKE_PID" 2>/dev/null || true
  done
  if kill -0 "$SMOKE_PID" 2>/dev/null; then
    echo "⚠️ 冒煙測試用的 App 10 秒內沒結束，改用 KILL" >&2
    kill -9 "$SMOKE_PID" 2>/dev/null || true
  fi
  wait "$SMOKE_PID" 2>/dev/null || true
  echo "✅ 冒煙測試：無 LANG 啟動 8 秒仍在跑"
else
  echo "❌ 冒煙測試：無 LANG 啟動後自己結束，看 $SMOKE_LOG" >&2
  tail -20 "$SMOKE_LOG" >&2
  exit 1
fi

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
