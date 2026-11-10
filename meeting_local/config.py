"""集中管理路徑與預設值。全部可用環境變數覆蓋（MEETING_LOCAL_*）。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import models as _models

APP_NAME = "Echoic 本機版"
HOME = Path.home()
FROZEN = bool(getattr(sys, "frozen", False))
# PyInstaller 解開後的資源根目錄。開發模式不使用這個路徑，避免本機 CLI
# 和已封裝的 App 走出不同的預設行為。
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BUNDLED_BIN = BUNDLE_ROOT / "bin"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


# 模型：先找現成的，找不到才下載到共用資料夾（和「看懂」共用，見 models.py）。
SHARED_MODELS_DIR = _models.shared_dir(HOME)
# 也認舊位置：0.1.x 安裝版的模型資料夾、已裝 Memo.app 的模型、看懂的快取。只讀，不搬不改。
_LEGACY_MODEL_DIRS = [
    HOME / "Library/Application Support/會議大師/models",
    HOME / "Library/Application Support/Memo/models",
    HOME / ".cache/kandong/models",
    HOME / ".cache/floattranslate/whisper",  # 看懂／FloatTranslate 舊版的語音辨識快取（放 q5_0）
]
WHISPER_SEARCH_DIRS = [SHARED_MODELS_DIR, *_LEGACY_MODEL_DIRS]
_MEMO_WHISPER_BIN = Path("/Applications/Memo.app/Contents/Resources/addon/whisper/bin/1.8.6/whisper-server")
_MEMO_VAD_MODEL = Path("/Applications/Memo.app/Contents/Resources/addon/vad/ggml-silero-v6.2.0.bin")


def _default_whisper_server() -> Path:
    """安裝版用內附的 whisper-server（build 腳本從 whisper.cpp 原始碼自建，arm64＋Metal）。
    開發模式依序找：已裝的 Memo.app 內建版、PATH 上的 whisper-server（Homebrew ARM 版）。"""
    if FROZEN:
        return BUNDLED_BIN / "whisper-server"
    if _MEMO_WHISPER_BIN.exists():
        return _MEMO_WHISPER_BIN
    found = shutil.which("whisper-server")
    return Path(found) if found else BUNDLED_BIN / "whisper-server"


def _default_vad_model() -> Path:
    for p in (SHARED_MODELS_DIR / VAD_MODEL_FILENAME, _LEGACY_MODEL_DIRS[0] / VAD_MODEL_FILENAME, _MEMO_VAD_MODEL):
        if p.is_file():
            return p
    return SHARED_MODELS_DIR / VAD_MODEL_FILENAME


VAD_MODEL_FILENAME = "ggml-silero-v6.2.0.bin"
# 預設下載未量化版（現有參數都是用它實測的）；已經有 q5_0（例如裝過看懂）就直接用，不再下載。
WHISPER_DOWNLOAD_FILE = "ggml-large-v3-turbo.bin"
WHISPER_SERVER = _env_path("MEETING_LOCAL_WHISPER_SERVER", _default_whisper_server())
WHISPER_MODEL = _env_path(
    "MEETING_LOCAL_WHISPER_MODEL",
    _models.find_whisper(WHISPER_SEARCH_DIRS) or SHARED_MODELS_DIR / WHISPER_DOWNLOAD_FILE,
)
VAD_MODEL = _env_path("MEETING_LOCAL_VAD_MODEL", _default_vad_model())
WHISPER_PORT = int(os.environ.get("MEETING_LOCAL_WHISPER_PORT", "9589"))
# 2026-11-10 實測（M4，4 效能核＋6 節能核；whisper 主要跑在 GPU）：8 → 4 執行緒推論時間不變（25–30 秒／6 分鐘音檔），
# 前景 CPU 小工作延遲回到閒置水準。taskpolicy -b（背景 QoS）反而讓前景更慢（中位 7.6 → 26–29 ms），不用。
WHISPER_THREADS = int(os.environ.get("MEETING_LOCAL_WHISPER_THREADS", "4"))
# 「背景」速度：whisper 少用執行緒、說話人分離單執行緒，兩支子程序都 nice 降優先權（只降子程序，不動視窗）。
WHISPER_THREADS_BACKGROUND = int(os.environ.get("MEETING_LOCAL_WHISPER_THREADS_BACKGROUND", "2"))
DIARIZE_THREADS = int(os.environ.get("MEETING_LOCAL_DIARIZE_THREADS", "2"))
BACKGROUND_NICE = int(os.environ.get("MEETING_LOCAL_BACKGROUND_NICE", "10"))
WHISPER_LANGUAGE = os.environ.get("MEETING_LOCAL_LANGUAGE", "zh")
# 初始提示：把 whisper 往「台灣、繁體」推；同音專名仍要靠事後的專名候選表。
DEFAULT_PROMPT = os.environ.get("MEETING_LOCAL_PROMPT", "以下是台灣的會議錄音，請以繁體中文逐字記錄。")
# whisper 初始提示的長度上限（字）：whisper 只保留 prompt 的最後約 224 個 token，塞太多反而把開頭擠掉。
WHISPER_PROMPT_MAX_CHARS = int(os.environ.get("MEETING_LOCAL_PROMPT_MAX", "180"))
# VAD 預設關：2026-10-05 回看三週會議，錄音偏小聲時 VAD 把講話當靜音整段丟掉（10/04 關掉多拿回 26% 字數、
# 10/05 另一場 66%）。關 VAD 必配 max-context 0，否則幻覺迴圈從 2 組變 24 組。MEETING_LOCAL_VAD=1 可開回來。
WHISPER_VAD = os.environ.get("MEETING_LOCAL_VAD", "0") == "1"
WHISPER_MAX_CONTEXT = int(os.environ.get("MEETING_LOCAL_MAX_CONTEXT", "0"))
# 轉錄前先做響度正規化（EBU R128，-18 LUFS），原檔 audio.wav 不動，正規化後存 audio.norm.wav 給 whisper 與分離用。
NORMALIZE = os.environ.get("MEETING_LOCAL_NORMALIZE", "1") != "0"
LOUDNORM_FILTER = "loudnorm=I=-18:TP=-2:LRA=11"
# 錄音平均音量低於這個值才提醒「偏小聲」。2026-10-11 從 -30 降到 -40：內建麥克風錄會議室對面的人，講話平均就是 -35 上下，
# 輸入音量 83 或 54 只差兩三 dB，但正規化後逐字稿 0 空白分鐘；真的出事的是 10/4 那種 -43（訊噪差 6 dB）。
LOW_LEVEL_DB = float(os.environ.get("MEETING_LOCAL_LOW_LEVEL_DB", "-40"))
# 錄音開始前把 macOS 系統輸入音量拉到這個值（低於才動；0＝不碰）。Teams／Zoom 開完會會把它偷偷調低（實測 83→54→67）。
AUTO_INPUT_VOLUME = int(os.environ.get("MEETING_LOCAL_INPUT_VOLUME", "85"))
# 混音限幅：峰值壓在 -1 dBFS 以下，避免兩路相加削波（9/14、9/20 兩場峰值頂到 0.0 dB）。
LIMITER_FILTER = "alimiter=limit=0.891:attack=5:release=50:level=false"

# 輸出根目錄：錄音、逐字稿、摘要只留在這台電腦。
OUT_ROOT = _env_path("MEETING_LOCAL_OUT", HOME / "Downloads/meetings")
# 詞彙表：正確寫法進 whisper 提示、已知錯寫在逐字稿直接換掉、摘要照這裡寫。放 vault 根目錄，Obsidian 裡直接改。
GLOSSARY = _env_path("MEETING_LOCAL_GLOSSARY", OUT_ROOT / "詞彙表.md")
MODELS_DIR = _env_path("MEETING_LOCAL_MODELS", HOME / ".cache/meeting-local/models")

DEFAULT_FFMPEG = BUNDLED_BIN / "ffmpeg" if FROZEN else Path(shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg")
FFMPEG = os.environ.get("MEETING_LOCAL_FFMPEG") or str(DEFAULT_FFMPEG)
FFPROBE = os.environ.get("MEETING_LOCAL_FFPROBE") or str(Path(FFMPEG).with_name("ffprobe"))

# 摘要（選用）走使用者自己登入的 Claude Code CLI：逐字稿只送進他自己的 Claude 帳號，不接其他雲端 API。
# 會用到他 Claude 方案的額度，所以預設不自動做，由設定檔 auto_summary 或 --summary 打開（見 settings.py）。
CLAUDE_BIN = os.environ.get("MEETING_LOCAL_CLAUDE") or shutil.which("claude") or str(HOME / ".local/bin/claude")
CLAUDE_MODEL = os.environ.get("MEETING_LOCAL_CLAUDE_MODEL")  # None = claude CLI 預設模型
SETTINGS_PATH = _env_path("MEETING_LOCAL_SETTINGS", HOME / ".config/echoic-local/settings.json")
# 線上語音辨識（選用）的 key：只放這個 0600 的檔（或環境變數 MEETING_LOCAL_STT_API_KEY），不進 settings.json。
STT_API_KEY_PATH = _env_path("MEETING_LOCAL_STT_API_KEY_FILE", SETTINGS_PATH.parent / "stt-api-key")
STT_CHUNK_SECONDS = float(os.environ.get("MEETING_LOCAL_STT_CHUNK_SECONDS", "600"))


def claude_available() -> bool:
    return Path(CLAUDE_BIN).is_file()

# 台灣正體 gate（開發者機器上的檢查腳本；不存在就跳過）。
TW_GATE = _env_path("MEETING_LOCAL_TW_GATE", HOME / ".claude/hooks/check-tw-wording.py")

# 說話人分離自動分群門檻（越大分出的人越少）。2026-09-14 實測：
#   39 分鐘真實會議 10 分鐘切片：0.5→126 群（全檔）、0.7→30、0.9→16（≥20 秒的 4 群）、1.1→6、1.3→2
#   合成兩人對話（TTS 兩種聲音）：0.9→2 人、1.1→1 人（併掉了）
# 取 0.9，零碎群（發言占比 < DIARIZE_MIN_SHARE）在指派時併入前後說話人。知道人數就用 --speakers N 最準。
# 2026-10-05 三週 10 場真實會議回看：0.9 先切出 30–89 群再靠併入壓到 6–13 人，實際 2–5 人；提到 1.1。
# 知道人數一律用 --speakers N（或 UI 填與會者），門檻只在不知道人數時用。
DIARIZE_THRESHOLD = float(os.environ.get("MEETING_LOCAL_DIARIZE_THRESHOLD", "1.1"))
DIARIZE_MIN_SHARE = float(os.environ.get("MEETING_LOCAL_DIARIZE_MIN_SHARE", "0.02"))

# 模型一律從官方網址下載，比對官方 SHA256。下載只會在 UI 裡使用者明確按下按鈕後發生。
VAD_MODEL_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin"
VAD_MODEL_SHA256 = "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
VAD_MODEL_SIZE = 885_098


def download_whisper_models(progress=None) -> None:
    """下載缺的模型到共用資料夾；已經有（含看懂下載過的 q5_0 版）就跳過。"""
    global WHISPER_MODEL, VAD_MODEL
    if not WHISPER_MODEL.is_file():
        # 指定了清單裡的檔名（MEETING_LOCAL_WHISPER_MODEL）就下載到指定位置，否則下載到共用資料夾
        known = {e.file for e in _models.entries()}
        target = WHISPER_MODEL if WHISPER_MODEL.name in known else SHARED_MODELS_DIR / WHISPER_DOWNLOAD_FILE
        e = _models.entry(target.name)
        WHISPER_MODEL = _models.download(e.url, target, e.sha256, e.size, "語音辨識模型", progress)
    if not VAD_MODEL.is_file():
        VAD_MODEL = _models.download(VAD_MODEL_URL, SHARED_MODELS_DIR / VAD_MODEL_FILENAME, VAD_MODEL_SHA256,
                                     VAD_MODEL_SIZE, "VAD 模型", progress)
    if progress:
        progress("✅ 模型已就緒")

# sherpa-onnx 說話人分離模型（curl 下載，不走 python https：這台 Python 缺 CA bundle）。
SEG_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
SEG_MODEL_DIRNAME = "sherpa-onnx-pyannote-segmentation-3-0"
EMB_MODEL_FILENAME = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
EMB_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/" + EMB_MODEL_FILENAME  # 上游網址就是拼成 recongition
)
