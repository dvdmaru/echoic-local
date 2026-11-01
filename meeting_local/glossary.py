"""詞彙表：一份常駐的 `詞彙表.md`（放在輸出資料夾根目錄），三個地方共用。

1. whisper 初始提示：把正確寫法塞進 prompt，模型比較會選對字（prompt 有長度上限，只放正確寫法）。
2. 逐字稿後處理：已知的錯寫直接換成正確寫法（只換 2 字以上的錯寫，避免誤殺）。
3. 摘要與專名表：告訴 Claude 這些詞已確認，摘要用正確寫法、專名表不用再列。

格式（每行一條，`｜` 或 `|` 分欄；第一欄正確寫法，第二欄逐字稿常見錯寫，用「、」分開；第三欄備註可省）：
    - 晴光｜情光、晴廣｜產品名
    | 晴光 | 情光、晴廣 | 產品名 |
以 `#` 開頭的行與表頭、分隔線會略過。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE = """# 詞彙表（meeting-local 共用）

每場會議轉錄前都會讀這份檔：正確寫法會進 whisper 的提示、已知錯寫會在逐字稿裡直接換掉、摘要也會照這裡的寫法。
格式：一行一條，`正確寫法｜逐字稿常見錯寫（用、分開）｜備註`。錯寫只換 2 個字以上的，1 個字的不會自動換。
不確定的先別填錯寫欄，只填正確寫法也有幫助（whisper 會比較容易選對字）。

- 範例公司｜範力公司、犯例公司｜刪掉這行換成你的
"""

_SPLIT_COL = re.compile(r"[｜|]")
_SPLIT_VAR = re.compile(r"[、,，/／;；]")
_HEADER_WORDS = ("正確寫法", "正確", "canonical", "---", "錯寫")


@dataclass
class Term:
    canonical: str
    variants: list[str] = field(default_factory=list)
    note: str = ""


def parse(text: str) -> list[Term]:
    terms: list[Term] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        # 只收條目行：以 -／*／• 開頭的清單，或以 | 開頭的表格列；說明文字一律略過
        if not line or line.startswith("#") or line[0] not in "-*•|｜":
            continue
        line = line.lstrip("-*•").strip().strip("|｜").strip()
        if not line:
            continue
        cols = [c.strip() for c in _SPLIT_COL.split(line)]
        canonical = cols[0] if cols else ""
        if not canonical or canonical.lower() in _HEADER_WORDS or set(canonical) <= set("-:："):
            continue
        if canonical.startswith("範例") and "刪掉這行" in line:
            continue
        variants = []
        if len(cols) > 1:
            variants = [v.strip() for v in _SPLIT_VAR.split(cols[1]) if v.strip() and v.strip() != canonical]
        note = cols[2] if len(cols) > 2 else ""
        if canonical in seen:
            continue
        seen.add(canonical)
        terms.append(Term(canonical, variants, note))
    return terms


def load(path: Path) -> list[Term]:
    if not path.exists():
        return []
    return parse(path.read_text(encoding="utf-8", errors="replace"))


def ensure_file(path: Path) -> bool:
    """沒有就放一份範本，回傳是否新建。"""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


def whisper_prompt(base: str, terms: list[Term], max_chars: int = 180) -> str:
    """base 之後接「詞彙：A、B、C」，總長不超過 max_chars（whisper 初始提示有 token 上限，超過會被截掉前面）。"""
    if not terms:
        return base
    prefix = (base.rstrip() + " ") if base else ""
    head = prefix + "詞彙："
    budget = max_chars - len(head)
    picked: list[str] = []
    used = 0
    for t in terms:
        extra = len(t.canonical) + (1 if picked else 0)
        if used + extra > budget:
            break
        picked.append(t.canonical)
        used += extra
    if not picked:
        return base
    return head + "、".join(picked) + "。"


def apply(text: str, terms: list[Term], min_len: int = 2) -> tuple[str, int]:
    """把已知錯寫換成正確寫法；長的錯寫先換，避免短的吃掉長的。回 (新文字, 換了幾處)。"""
    mapping = {v: t.canonical for t in terms for v in t.variants if len(v) >= min_len and v != t.canonical}
    if not mapping:
        return text, 0
    # 一次掃描、長的優先：換出來的正確寫法不會再被別條錯寫吃掉
    pattern = re.compile("|".join(re.escape(v) for v in sorted(mapping, key=len, reverse=True)))
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        return mapping[m.group(0)]

    return pattern.sub(sub, text), n


def markdown_block(terms: list[Term]) -> str:
    """給 Claude 看的已確認詞彙（摘要與專名表共用）。沒有詞就回空字串。"""
    if not terms:
        return ""
    lines = ["| 正確寫法 | 逐字稿常見錯寫 | 備註 |", "|---|---|---|"]
    for t in terms:
        lines.append(f"| {t.canonical} | {'、'.join(t.variants) or '–'} | {t.note or ''} |")
    return "\n".join(lines)
