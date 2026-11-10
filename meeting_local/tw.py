"""簡→台灣正體（OpenCC s2twp）＋ 台灣用語 gate。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import config

_cc = None

# s2twp 的臺灣用語表（TWPhrasesIT）是為電腦文件寫的，套在會議口語上會改錯詞、甚至改掉意思。
# 2026-11-05 實跑：一場廣告會議的「腳本」21 處全被改成「指令碼」（繁體輸入也照轉）。
# 這幾個詞轉換時保持原樣（統一成正體寫法），其他大陸用語照常轉。
# 改成只轉字形的 s2tw 不行：視頻、軟件、信息、默認、服務器會原樣漏出來。
# 後面接特定字的複合詞仍交給 OpenCC（程序員→程式設計師、文件夾→資料夾、數據庫→資料庫）。
_KEEP = [
    (re.compile(r"[脚腳]本"), "腳本"),            # 不是「指令碼」
    (re.compile(r"文件(?![夹夾])"), "文件"),        # 不是「檔案」
    (re.compile(r"程序(?![员員])"), "程序"),        # 法律程序、申請程序不是「程式」
    (re.compile(r"[点點][击擊]率"), "點擊率"),      # 廣告業界用語，不是「點選率」
    (re.compile(r"[数數][据據](?![库庫])"), "數據"),  # 不是「資料」
    (re.compile(r"[优優]化"), "優化"),              # 不是「最佳化」
]
_PH = 0xE000  # Unicode 私用區字元當佔位符，OpenCC 不會動它


def to_tw(text: str) -> str:
    global _cc
    if _cc is None:
        from opencc import OpenCC  # opencc-python-reimplemented

        _cc = OpenCC("s2twp")
    for i, (pat, _) in enumerate(_KEEP):
        text = pat.sub(chr(_PH + i), text)
    text = _cc.convert(text)
    for i, (_, word) in enumerate(_KEEP):
        text = text.replace(chr(_PH + i), word)
    return text


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
