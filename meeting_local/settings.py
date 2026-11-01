"""使用者設定（小 JSON 檔）。目前只有一個：轉完逐字稿後要不要自動用 Claude 產生摘要。

摘要會用到使用者自己 Claude 方案的用量，所以預設關，讓他自己選。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config

DEFAULTS = {"auto_summary": False}

# 給 UI 與 README 共用的說明。數字來源：2026-09～10 實際 26 場會議，一小時逐字稿中位數約 2 萬字，
# 專名表與摘要各送一次（約 2 萬字＋2.5 萬字），回覆合計約 1 萬字。
SUMMARY_COST_NOTE = (
    "摘要用這台電腦上登入的 Claude Code 產生，會算進你自己 Claude 方案的用量："
    "一小時的會議大約送出 4～5 萬字、拿回約 1 萬字。"
    "用 Pro（每月 US$20）方案時，一天做好幾場長會議可能比較快碰到用量上限。"
    "不勾也能用：只出逐字稿，想要哪一場的摘要再按「產生這場摘要」。"
)


def load(path: Path | None = None) -> dict:
    path = path or config.SETTINGS_PATH
    data = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: raw[k] for k in DEFAULTS if k in raw})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return data


def save(values: dict, path: Path | None = None) -> None:
    path = path or config.SETTINGS_PATH
    data = load(path)
    data.update({k: values[k] for k in DEFAULTS if k in values})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def auto_summary(path: Path | None = None) -> bool:
    return bool(load(path)["auto_summary"])
