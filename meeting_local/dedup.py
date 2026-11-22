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


INNER_LOOP_MIN_CHARS = 30
INNER_LOOP_DISTINCT = 0.25


def inner_loop(text: str) -> bool:
    """同一段裡幾個字一直重複（2026-11-22 實例：7 秒的話回成「一二三四五六七八九十」×22，223 字只有 10 種字）。
    正常的句子 30 字以上，不同的字通常超過一半；短的「對對對」不算。"""
    body = normalize(text)
    return len(body) >= INNER_LOOP_MIN_CHARS and len(set(body)) / len(body) < INNER_LOOP_DISTINCT


def collapse_hallucinations(segments: list[Segment], min_run: int = 3) -> tuple[list[Segment], list[dict]]:
    """連續 ≥ min_run 段文字相同 → 合併成一段並標 [幻覺，已略]；單一段自己鬼打牆（inner_loop）也標。
    回傳 (新段落, 報告)。"""
    out: list[Segment] = []
    report: list[dict] = []
    i = 0
    n_total = len(segments)
    while i < n_total:
        if not segments[i].flag and inner_loop(segments[i].text):
            s = segments[i]
            original = s.text.strip()
            out.append(Segment(start=s.start, end=s.end, text=f"[幻覺，已略] 「{original[:20]}…」（同幾個字一直重複）",
                               flag="hallucination", meta={"original": original, "repeats": 1}))
            report.append({"start": s.start, "end": s.end, "start_clock": fmt_clock(s.start),
                           "end_clock": fmt_clock(s.end), "text": original[:60], "repeats": 1, "inner": True})
            i += 1
            continue
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


def merged_spans(runs: list[dict], lo: float = 0.0, hi: float | None = None) -> list[tuple[float, float]]:
    """幻覺區段夾在 [lo, hi] 內、重疊的併成一段，由早到晚。"""
    spans = []
    for r in runs:
        s, e = max(lo, float(r["start"])), float(r["end"])
        if hi is not None:
            e = min(hi, e)
        if e > s:
            spans.append((s, e))
    out: list[tuple[float, float]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def hallucination_coverage(runs: list[dict], duration: float, start: float = 0.0) -> float:
    """幻覺迴圈佔 [start, start+duration] 的比例（0～1；重疊的區段只算一次）。"""
    if not runs or not duration:
        return 0.0
    total = sum(e - s for s, e in merged_spans(runs, start, start + float(duration)))
    return min(1.0, total / float(duration))


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
