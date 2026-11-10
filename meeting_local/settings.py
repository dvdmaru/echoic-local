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
}

# 給 UI 與 README 共用的說明。數字來源：2026-09～10 實際 26 場會議，一小時逐字稿中位數約 2 萬字，
# 專名表與摘要各送一次（約 2 萬字＋2.5 萬字），回覆合計約 1 萬字。
SUMMARY_COST_NOTE = (
    "摘要用這台電腦上登入的 Claude Code 產生，會算進你自己 Claude 方案的用量："
    "一小時的會議大約送出 4～5 萬字、拿回約 1 萬字。"
    "用 Pro（每月 US$20）方案時，一天做好幾場長會議可能比較快碰到用量上限。"
    "不勾也能用：只出逐字稿，想要哪一場的摘要再按「產生這場摘要」。"
)


def _valid(key: str, value) -> bool:
    if key == "auto_summary":
        return isinstance(value, bool)
    if key == "stt_engine":
        return value in ENGINES
    if key == "local_speed":
        return value in LOCAL_SPEEDS
    if key in ("stt_api_base_url", "stt_api_model"):
        return isinstance(value, str) and bool(value.strip())
    return False


def load(path: Path | None = None) -> dict:
    path = path or config.SETTINGS_PATH
    data = dict(DEFAULTS)
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
