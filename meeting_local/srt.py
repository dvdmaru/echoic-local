"""SRT 讀寫與時間格式。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Segment:
    start: float  # 秒
    end: float
    text: str
    speaker: str | None = None
    flag: str | None = None  # None | "hallucination" | "suspect"
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


_TS = re.compile(
    r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)


def _to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(text: str) -> list[Segment]:
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if _TS.search(ln)), None)
        if ts_idx is None:
            continue
        m = _TS.search(lines[ts_idx])
        assert m
        start = _to_sec(*m.groups()[:4])
        end = _to_sec(*m.groups()[4:])
        body = " ".join(ln.strip() for ln in lines[ts_idx + 1 :]).strip()
        segments.append(Segment(start=start, end=end, text=body))
    return segments


def fmt_srt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_clock(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def render_srt(segments: list[Segment]) -> str:
    out = []
    for i, s in enumerate(segments, 1):
        prefix = f"[{s.speaker}] " if s.speaker else ""
        out.append(f"{i}\n{fmt_srt_ts(s.start)} --> {fmt_srt_ts(s.end)}\n{prefix}{s.text}\n")
    return "\n".join(out)
