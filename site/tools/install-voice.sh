#!/bin/bash
# Echoic 輸入法：一行安裝（https://echoic.twtools.cc/voice/install.sh）
#
# 這支腳本只做五件事：
#   1. 從 echoic.twtools.cc 下載最新版 EchoicVoice-mac-arm64.zip 與 SHA256SUMS.txt
#   2. 比對 SHA-256，不符就停止
#   3. 解壓縮，把「Echoic 輸入法.app」複製到「應用程式」（覆蓋舊版；正在執行的話先關掉）
#   4. 刪掉暫存檔
#   5. 打開 App
#
# 為什麼用指令裝就不會跳「無法打開」：這個 App 沒有付費的 Apple 公證。用瀏覽器下載的檔案會被 macOS
# 標上「從網路下載」，第一次打開就會被擋；用 curl 下載不會有這個標記。等於你自己決定相信這個 App。
#
# App 不含任何 API key：辨識用你自己在「設定…」貼上的 key，只存在你的電腦（~/.config/echoic-voice/）。
#
# 想先看內容再執行：
#   curl -fsSL https://echoic.twtools.cc/voice/install.sh -o install.sh
#   less install.sh
#   bash install.sh
set -euo pipefail

ZIP="EchoicVoice-mac-arm64.zip"
APP="Echoic 輸入法.app"
BASE="${ECHOIC_VOICE_BASE:-https://echoic.twtools.cc/voice}"
APPS="${ECHOIC_APPS_DIR:-/Applications}"
DEST="${APPS}/${APP}"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "❌ 只支援 macOS。" >&2; exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "❌ 只支援 Apple Silicon（M 系列晶片）的 Mac。" >&2; exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "⬇️  下載最新版（不到 1 MB）…"
curl -fL --progress-bar -o "${TMP}/${ZIP}" "${BASE}/${ZIP}"
curl -fsSL -o "${TMP}/SHA256SUMS.txt" "${BASE}/SHA256SUMS.txt"

want="$(awk -v f="${ZIP}" '$2 == f { print $1 }' "${TMP}/SHA256SUMS.txt")"
got="$(shasum -a 256 "${TMP}/${ZIP}" | awk '{ print $1 }')"
if [ -z "${want}" ] || [ "${want}" != "${got}" ]; then
  echo "❌ 檔案的 SHA-256 和官方公布的不符，已停止安裝（沒有動到你的電腦）。" >&2; exit 1
fi
echo "✅ SHA-256 相符：${got}"

ditto -x -k "${TMP}/${ZIP}" "${TMP}/x"
if [ ! -d "${TMP}/x/${APP}" ]; then
  echo "❌ 壓縮檔裡找不到 ${APP}，已停止安裝。" >&2; exit 1
fi

# 正在執行就先關掉（它只是選單列小工具，關掉不會丟資料）
if [ -z "${ECHOIC_APPS_DIR:-}" ]; then
  osascript -e 'quit app "Echoic 輸入法"' >/dev/null 2>&1 || true
  sleep 1
fi

mkdir -p "${APPS}"
# 先複製到旁邊再換，複製失敗不會留下壞掉的一半
ditto "${TMP}/x/${APP}" "${APPS}/.${APP}.new"
rm -rf "${DEST}"
mv "${APPS}/.${APP}.new" "${DEST}"
echo "✅ 已安裝到 ${DEST}"

if [ -z "${ECHOIC_NO_OPEN:-}" ]; then
  open "${DEST}"
  echo "👉 選單列會出現「〰 OpenAI」。第一次開會跳出設定視窗：貼上你自己的 API key、按「測試目前引擎」。"
  echo "   要自動貼上文字，請到「系統設定 › 隱私權與安全性 › 輔助使用」打開「Echoic 輸入法」。"
fi
