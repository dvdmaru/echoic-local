"""whisper 幻覺迴圈去重：靜音／雜音段會把同一句重複上百次。"""
from __future__ import annotations

import unicodedata

from .srt import Segment, fmt_clock

# 只放強訊號；「訂閱」這種商務會議也會講的字不放。
SUSPECT_PATTERNS = (
    "字幕由",
    "amara",
    "請不吝點贊",
    "點贊訂閱",
    "訂閱轉發",
    "打賞支持",
    "明鏡與點點",
    "謝謝觀看",
    "謝謝收看",
    "感謝觀看",
)


def normalize(text: str) -> str:
    """去掉標點、空白、符號與控制字元，全部小寫，用來判斷「同一句」。"""
    return "".join(
        ch for ch in text if not unicodedata.category(ch)[0] in ("P", "Z", "S", "C")
    ).lower()


def collapse_hallucinations(segments: list[Segment], min_run: int = 3) -> tuple[list[Segment], list[dict]]:
    """連續 ≥ min_run 段文字相同 → 合併成一段並標 [幻覺，已略]。回傳 (新段落, 報告)。"""
    out: list[Segment] = []
    report: list[dict] = []
    i = 0
    n_total = len(segments)
    while i < n_total:
        key = normalize(segments[i].text)
        j = i
        while key and j + 1 < n_total and normalize(segments[j + 1].text) == key:
            j += 1
        run = j - i + 1
        if run >= min_run:
            first, last = segments[i], segments[j]
            original = first.text.strip()
            merged = Segment(
                start=first.start,
                end=last.end,
                text=f"[幻覺，已略] 「{original}」×{run}",
                flag="hallucination",
                meta={"original": original, "repeats": run},
            )
            out.append(merged)
            report.append(
                {
                    "start": first.start,
                    "end": last.end,
                    "start_clock": fmt_clock(first.start),
                    "end_clock": fmt_clock(last.end),
                    "text": original,
                    "repeats": run,
                }
            )
        else:
            out.extend(segments[i : j + 1])
        i = j + 1
    return out, report


def flag_suspects(segments: list[Segment]) -> list[Segment]:
    """常見的 YouTube 式幻覺句：保留原文，只加註 suspect。"""
    hits = []
    for s in segments:
        if s.flag:
            continue
        low = s.text.lower()
        if any(p.lower() in low for p in SUSPECT_PATTERNS):
            s.flag = "suspect"
            hits.append(s)
    return hits
