"""會議索引：掃 ~/Downloads/meetings 底下每場會議的資料夾，產一份 Obsidian 讀得懂的 會議索引.md。

不需要任何 Obsidian 外掛：wikilink 直接連到 summary.md；未完成待辦用 `- [ ]` 原樣列出。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

INDEX_NAME = "會議索引.md"
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})(?:-(.*))?$")
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_TODO = re.compile(r"^- \[ \] (.+?)\s*$", re.M)


@dataclass
class MeetingRow:
    folder: Path
    date: str
    clock: str
    title: str
    duration_min: float | None
    speakers: int | None
    todos: list[str] = field(default_factory=list)
    stage: str = "只有錄音"

    @property
    def name(self) -> str:
        return self.folder.name


def _fmt_min(sec: float | None) -> str:
    if sec is None:
        return "–"
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m}:{s:02d}"


def scan(out_root: Path) -> list[MeetingRow]:
    rows: list[MeetingRow] = []
    for folder in sorted(out_root.iterdir(), reverse=True):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        wav = folder / "audio.wav"
        summary = folder / "summary.md"
        transcript = folder / "transcript-by-minute.txt"
        run = folder / "run.json"
        if not (wav.exists() or summary.exists() or transcript.exists()):
            continue
        data: dict = {}
        if run.exists():
            try:
                data = json.loads(run.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        m = _STAMP.match(folder.name)
        if m:
            date, clock = m.group(1), f"{m.group(2)}:{m.group(3)}"
        else:
            mt = time.localtime((wav if wav.exists() else folder).stat().st_mtime)
            date, clock = time.strftime("%Y-%m-%d", mt), time.strftime("%H:%M", mt)
        title = data.get("title") or ""
        todos: list[str] = []
        if summary.exists():
            text = summary.read_text(encoding="utf-8", errors="replace")
            if not title:
                tm = _TITLE.search(text)
                title = re.sub(r"（\d{4}-\d{2}-\d{2} \d{2}:\d{2}）$", "", tm.group(1)).strip() if tm else ""
            todos = _TODO.findall(text)
        if not title:
            title = (m.group(4) if m and m.group(4) else folder.name)
        duration = None
        audio = data.get("audio") or {}
        if isinstance(audio, dict) and audio.get("duration"):
            duration = float(audio["duration"])
        elif isinstance(data.get("record"), dict) and data["record"].get("duration"):
            duration = float(data["record"]["duration"])
        speakers = data.get("speakers")
        n_speakers = len(speakers) if isinstance(speakers, dict) and speakers else None
        stage = "摘要完成" if summary.exists() else ("逐字稿完成" if transcript.exists() else "只有錄音")
        rows.append(MeetingRow(folder, date, clock, title, duration, n_speakers, todos, stage))
    rows.sort(key=lambda r: (r.date, r.clock), reverse=True)  # 最新在上，不管資料夾叫什麼
    return rows


def render(rows: list[MeetingRow], out_root: Path) -> str:
    lines = [
        "# 會議索引",
        "",
        f"最後更新：{time.strftime('%Y-%m-%d %H:%M')}｜共 {len(rows)} 場｜本檔由 `meeting-local index` 自動產生，手改會被覆蓋；筆記請寫在各場的 summary.md 或另開檔案。",
        "",
        "| 日期 | 時間 | 標題 | 時長 | 說話人 | 待辦 | 狀態 | 檔案 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        links = []
        if (r.folder / "summary.md").exists():
            links.append(f"[[{r.name}/summary\\|摘要]]")
        if (r.folder / "transcript-by-minute.txt").exists():
            links.append(f"[[{r.name}/transcript-by-minute.txt\\|逐字稿]]")
        if (r.folder / "entities.md").exists():
            links.append(f"[[{r.name}/entities\\|專名]]")
        open_todos = len(r.todos)
        title = r.title.replace("|", "｜")
        lines.append(
            f"| {r.date} | {r.clock} | {title} | {_fmt_min(r.duration_min)} | "
            f"{r.speakers if r.speakers is not None else '–'} | {open_todos or '–'} | {r.stage} | {' '.join(links) or '–'} |"
        )
    todo_rows = [(r, t) for r in rows for t in r.todos]
    lines += ["", "## 未完成待辦（所有會議）", ""]
    if todo_rows:
        lines.append("勾掉請到該場的 summary.md 勾，這裡下次重建索引會跟著更新。")
        lines.append("")
        for r, t in todo_rows:
            lines.append(f"- [ ] {t} ｜ [[{r.name}/summary\\|{r.date} {r.title}]]")
    else:
        lines.append("（目前沒有）")
    lines += ["", "## 怎麼用", "",
              "- 錄音／轉錄／摘要：終端機 `meeting-local ui`，或 `meeting-local all <資料夾>`。",
              "- 專名錯字：打開該場 `entities.md` 填「確認正解」，再 `meeting-local summarize <資料夾>`。",
              "- 重建這份索引：`meeting-local index`（每次跑完管線也會自動更新）。",
              f"- 這個資料夾只在這台電腦（{out_root}），不會自動上傳到任何雲端。", ""]
    return "\n".join(lines)


def write_index(out_root: Path) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    rows = scan(out_root)
    path = out_root / INDEX_NAME
    path.write_text(render(rows, out_root), encoding="utf-8")
    return path
