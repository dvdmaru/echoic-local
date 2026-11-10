#!/bin/bash
# Echoic 本機版：一行安裝（https://echoic.twtools.cc/install.sh）
#
# 這支腳本只做五件事：
#   1. 從 GitHub Releases 下載最新版 EchoicLocal-mac-arm64.dmg 與 SHA256SUMS.txt
#   2. 比對 SHA-256，不符就停止
#   3. 掛載 dmg，把「Echoic 本機版.app」複製到「應用程式」（覆蓋舊版）
#   4. 卸載 dmg、刪掉暫存檔
#   5. 打開 App
#
# 為什麼用指令裝就不會跳「無法打開」：這個 App 沒有付費的 Apple 公證。用瀏覽器下載的檔案會被 macOS
# 標上「從網路下載」，第一次打開就會被擋；用 curl 下載不會有這個標記。等於你自己決定相信這個 App。
#
# 想先看內容再執行：
#   curl -fsSL https://echoic.twtools.cc/install.sh -o install.sh
#   less install.sh
#   bash install.sh
set -euo pipefail

REPO="dvdmaru/echoic-local"
DMG="EchoicLocal-mac-arm64.dmg"
APP="Echoic 本機版.app"
BASE="${ECHOIC_RELEASE_BASE:-https://github.com/${REPO}/releases/latest/download}"
APPS="${ECHOIC_APPS_DIR:-/Applications}"
DEST="${APPS}/${APP}"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "❌ 只支援 macOS。" >&2; exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "❌ 只支援 Apple Silicon（M 系列晶片）的 Mac。" >&2; exit 1
fi
if pgrep -f "${DEST}/Contents/MacOS/" >/dev/null 2>&1; then
  echo "❌ Echoic 本機版正在執行，請先關掉再安裝（錄音中的話先按停止）。" >&2; exit 1
fi

TMP="$(mktemp -d)"
MNT=""
cleanup() {
  if [ -n "${MNT}" ]; then hdiutil detach -quiet "${MNT}" >/dev/null 2>&1 || true; fi
  rm -rf "${TMP}"
}
trap cleanup EXIT

echo "⬇️  下載最新版（約 55 MB）…"
curl -fL --progress-bar -o "${TMP}/${DMG}" "${BASE}/${DMG}"
curl -fsSL -o "${TMP}/SHA256SUMS.txt" "${BASE}/SHA256SUMS.txt"

want="$(awk -v f="${DMG}" '$2 == f { print $1 }' "${TMP}/SHA256SUMS.txt")"
got="$(shasum -a 256 "${TMP}/${DMG}" | awk '{ print $1 }')"
if [ -z "${want}" ] || [ "${want}" != "${got}" ]; then
  echo "❌ 檔案的 SHA-256 和官方公布的不符，已停止安裝（沒有動到你的電腦）。" >&2; exit 1
fi
echo "✅ SHA-256 相符：${got}"

# macOS 27 起 hdiutil 會印「已棄用」警告（功能照常），藏掉免得看起來像出錯；真的失敗時下面的檢查會說
MNT="$(hdiutil attach -nobrowse -readonly -noautoopen "${TMP}/${DMG}" 2>/dev/null | awk -F '\t' '/\/Volumes\// { print $NF }' | tail -1)"
if [ -z "${MNT}" ] || [ ! -d "${MNT}/${APP}" ]; then
  echo "❌ dmg 裡找不到 ${APP}，已停止安裝。" >&2; exit 1
fi

# 先複製到旁邊，成功了才換掉舊版：中途失敗不會讓你連舊版都沒有
mkdir -p "${APPS}"
NEW="${APPS}/.echoic-local-new.app"
rm -rf "${NEW}"
if ! ditto "${MNT}/${APP}" "${NEW}"; then
  echo "❌ 無法寫入 ${APPS}。這個帳號不是管理者的話，請改用網站上的手動安裝步驟。" >&2; exit 1
fi
xattr -dr com.apple.quarantine "${NEW}" 2>/dev/null || true
rm -rf "${DEST}"
mv "${NEW}" "${DEST}"

version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "${DEST}/Contents/Info.plist" 2>/dev/null || echo '?')"
echo "✅ 已安裝 Echoic 本機版 ${version} → ${DEST}"
if [ -z "${ECHOIC_NO_OPEN:-}" ]; then
  open "${DEST}"
fi
