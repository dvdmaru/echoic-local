"""簡→台灣正體（OpenCC s2twp）＋ 台灣用語 gate。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import config

_cc = None


def to_tw(text: str) -> str:
    global _cc
    if _cc is None:
        from opencc import OpenCC  # opencc-python-reimplemented

        _cc = OpenCC("s2twp")
    return _cc.convert(text)


_CJK = r"[㐀-鿿＀-￯]"
_HALF2FULL = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}
_PUNCT_RE = re.compile(rf"(?<={_CJK})\s*([,?!:;])\s*|([,?!:;])\s*(?={_CJK})")


def fix_punct(text: str) -> str:
    """whisper 常輸出半形逗號問號；只在緊貼中文字時換成全形，英文句子不動。"""
    def _sub(m: re.Match) -> str:
        ch = m.group(1) or m.group(2)
        return _HALF2FULL[ch]

    text = _PUNCT_RE.sub(_sub, text)
    # 全形標點後面多餘空白拿掉
    return re.sub(r"([，？！：；])\s+(?=" + _CJK + ")", r"\1", text)


def run_tw_gate(path: Path) -> tuple[int | None, str]:
    """跑開發者機器上的 check-tw-wording.py --scan（台灣用語檢查）。回 (exit code, 輸出)；沒有腳本回 (None, 說明)。"""
    gate = config.TW_GATE
    if not gate.exists():
        return None, f"（tw gate 略過：找不到 {gate}）"
    proc = subprocess.run(
        ["python3", str(gate), "--scan", str(path)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode, out
