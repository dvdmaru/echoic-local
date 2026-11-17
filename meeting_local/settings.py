"""使用者設定（小 JSON 檔）。

- auto_summary：轉完逐字稿後要不要自動用 Claude 產生摘要。會用到使用者自己 Claude 方案的用量，預設關。
- stt_engine：語音辨識用本機 whisper（local，預設）或線上 API（api）。線上會上傳錄音，使用者自己選。
- stt_api_base_url／stt_api_model：線上 API 的網址與模型（OpenAI 相容）。key 不在這裡，見 stt_api.save_key。
- local_speed：本機 whisper 要跑多快（見 LOCAL_SPEEDS）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config
from .stt_api import DEFAULT_BASE_URL, DEFAULT_MODEL

ENGINES = ("local", "api")
LOCAL_SPEEDS = ("fast", "background")

DEFAULTS = {
    "auto_summary": False,
    "stt_engine": "local",
    "stt_api_base_url": DEFAULT_BASE_URL,
    "stt_api_model": DEFAULT_MODEL,
    "local_speed": "fast",
    "update_check": True,       # 安裝版每天最多查一次 GitHub 有沒有新版（只連 GitHub、不送會議內容）
    "update_checked_at": 0.0,
    # 會議庫的分類欄位（使用者自訂；會議時間不用分類，直接用日期）
    "categories": ["客戶", "專案"],
    # 讓其他 AI 助理（Claude Desktop／Claude Code 等）透過 MCP 讀會議。預設關；只讀、不改任何檔。
    "mcp_enabled": False,
    "mcp_transcripts": True,     # 關掉＝只給摘要，不給逐字稿
    "mcp_scope": {},             # {"客戶": ["A 公司", "B 公司"]}＝只開放這些；空＝全部（仍排除標成「不給 AI 助理」的會議）
}

MAX_CATEGORIES = 6

# 給 UI 與 README 共用的說明。數字來源：2026-09～10 實際 26 場會議，一小時逐字稿中位數約 2 萬字，
# 專名表與摘要各送一次（約 2 萬字＋2.5 萬字），回覆合計約 1 萬字。
SUMMARY_COST_NOTE = (
    "摘要用這台電腦上登入的 Claude Code 產生，會算進你自己 Claude 方案的用量："
    "一小時的會議大約送出 4～5 萬字、拿回約 1 萬字。"
    "用 Pro（每月 US$20）方案時，一天做好幾場長會議可能比較快碰到用量上限。"
    "不勾也能用：只出逐字稿，想要哪一場的摘要再按「產生這場摘要」。"
)


def _valid(key: str, value) -> bool:
    if key == "categories":
        return (isinstance(value, list) and 0 < len(value) <= MAX_CATEGORIES
                and all(isinstance(v, str) and v.strip() for v in value)
                and len({v.strip() for v in value}) == len(value))
    if key == "mcp_scope":
        return isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v) for k, v in value.items())
    if key in ("auto_summary", "update_check", "mcp_enabled", "mcp_transcripts"):
        return isinstance(value, bool)
    if key == "update_checked_at":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if key == "stt_engine":
        return value in ENGINES
    if key == "local_speed":
        return value in LOCAL_SPEEDS
    if key in ("stt_api_base_url", "stt_api_model"):
        return isinstance(value, str) and bool(value.strip())
    return False


def load(path: Path | None = None) -> dict:
    path = path or config.SETTINGS_PATH
    data = json.loads(json.dumps(DEFAULTS))  # 深拷貝：categories／mcp_scope 是可變物件，別讓呼叫端改到預設值
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: raw[k] for k in DEFAULTS if k in raw and _valid(k, raw[k])})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return data


def save(values: dict, path: Path | None = None) -> None:
    path = path or config.SETTINGS_PATH
    data = load(path)
    data.update({k: values[k] for k in DEFAULTS if k in values and _valid(k, values[k])})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def auto_summary(path: Path | None = None) -> bool:
    return bool(load(path)["auto_summary"])
