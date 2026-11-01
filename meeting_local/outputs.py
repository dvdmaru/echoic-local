"""輸出檔：transcript.srt／transcript-by-minute.txt／speakers.json／run.json。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .srt import Segment, fmt_clock, render_srt


def write_srt(path: Path, segments: list[Segment]) -> None:
    path.write_text(render_srt(segments), encoding="utf-8")


def by_minute_text(segments: list[Segment], source: str, halluc_report: list[dict]) -> str:
    lines = [f"# 逐分鐘逐字稿（來源：{source}）", "# 說話人為機器分離的 SPEAKER_xx，命名靠人；[幻覺，已略] 段為 whisper 迴圈重複，已合併。", ""]
    if halluc_report:
        lines.append("# 幻覺段落留痕：")
        for r in halluc_report:
            lines.append(f"#   {r['start_clock']}–{r['end_clock']} 「{r['text']}」×{r['repeats']}")
        lines.append("")
    current_minute = -1
    buffer: list[str] = []
    buf_speaker: str | None = None
    buf_start: float = 0.0

    def flush() -> None:
        nonlocal buffer, buf_speaker
        if buffer:
            who = f"{buf_speaker}：" if buf_speaker else ""
            lines.append(f"[{fmt_clock(buf_start)}] {who}{' '.join(buffer)}")
        buffer = []
        buf_speaker = None

    for s in segments:
        minute = int(s.start // 60)
        if minute != current_minute:
            flush()
            current_minute = minute
            lines.append("")
            lines.append(f"## {minute // 60:02d}:{minute % 60:02d}")
        if s.flag == "hallucination":
            flush()
            lines.append(f"⚠️ [{fmt_clock(s.start)}–{fmt_clock(s.end)}] {s.text}")
            continue
        text = s.text.strip()
        if s.flag == "suspect":
            text = f"{text} ⚠️[疑似幻覺]"
        if buffer and s.speaker == buf_speaker:
            buffer.append(text)
        else:
            flush()
            buffer = [text]
            buf_speaker = s.speaker
            buf_start = s.start
    flush()
    return "\n".join(lines).rstrip() + "\n"


def write_by_minute(path: Path, segments: list[Segment], source: str, halluc_report: list[dict]) -> None:
    path.write_text(by_minute_text(segments, source, halluc_report), encoding="utf-8")


def write_speakers_json(path: Path, diar: list[dict], talk: dict[str, float], models: dict) -> None:
    payload = {
        "num_speakers": len(talk),
        "talk_time_sec": talk,
        "note": "SPEAKER_xx 只是聚類編號，誰是誰請人工對照後填在 summary.md／entities.md。",
        "models": models,
        "segments": diar,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_run_json(path: Path, **fields) -> dict:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data.update(fields)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
