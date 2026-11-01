"""專名候選表＋摘要（選用）：走使用者自己登入的 `claude -p`。

逐字稿只送進使用者自己的 Claude 帳號，這裡不接任何其他家的雲端 API。
會用到使用者 Claude 方案的用量，所以預設不自動做（見 settings.py）。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from . import config
from .srt import Segment, fmt_clock

ENTITY_SYSTEM = """你是台灣會議逐字稿的「專名審核」助理。逐字稿由 whisper 本機轉出，常把同音專名寫錯（例：輝達→揮達、聯發科→連發科、PowerPoint→Power Point）。
任務：只列出「候選專名」讓人確認，不要摘要、不要評論。
候選類型：人名／公司或品牌／產品、專案、活動名／英文縮寫或英文詞／疑似同音錯寫的詞。
規則：
1. 只列逐字稿裡真的出現的字串（candidate 必須逐字可在逐字稿中找到）。
2. likely 欄寫你推測的正確寫法；沒把握就寫「未確認」，不要硬猜。
3. 每個候選附 1–3 個出現的時間戳（格式 HH:MM:SS，取自逐字稿行首）。
4. 同一個專名的不同錯寫合併成一列，candidate 用「A／B」列出各種寫法。
5. 輸入若附「已確認詞彙表」，表裡的詞與其錯寫已經處理過，不要再列。
只輸出一個 JSON 陣列，放在 ```json 圍欄內，元素格式：
{"candidate": "...", "type": "...", "likely": "...", "reason": "...", "timestamps": ["HH:MM:SS"]}"""

SUMMARY_SYSTEM = """你是台灣的會議記錄助理。輸入是本機 whisper 轉出的逐分鐘逐字稿（含 SPEAKER_xx 機器分離標記）與一張「專名確認表」。
輸出繁體中文（台灣用語）的會議摘要，Markdown，結構固定如下、順序不可變、不可增減：

# <會議標題>
## 一句話
## 決議
## 待辦
## 數字表
## 未確認專名
## 品質註記

硬規則：
0. 第一行「# <會議標題>」由你根據內容決定：8 到 20 字、具體（主題＋這場的重點或結論），不要寫「會議摘要」「會議記錄」這種泛稱，不要加日期（程式會自己加時間戳）。
1. 只根據逐字稿寫，逐字稿沒說的不要補。不確定就寫「未確認」，不要推論成定案。
2. 決議、待辦、數字每一條都附時間戳（[HH:MM:SS]），讓人能回去聽原音。
3. 專名確認表「確認正解」欄有填的，一律改用填的寫法；沒填的沿用逐字稿原字，並列進「未確認專名」。
4. 待辦格式：- [ ] 事項｜負責人：X｜時間：Y｜[HH:MM:SS]。逐字稿沒指名就寫「未指定」。
5. 數字表用 Markdown 表格：| 數字 | 指什麼 | 誰說的（SPEAKER_xx） | 時間戳 |。金額、數量、日期、百分比、期限都算。
6. 「品質註記」列：幻覺段落、聽不清處、說話人分離看起來混亂的區段。
7. 不要用「本次會議圓滿」這類套話；不要加免責聲明。
8. 輸入若附「與會者」名單：SPEAKER_xx 機器標記在真實會議常不可靠，請依內容推定是誰在說（誰在問、誰在答、誰拍板、
   誰自稱什麼），決議、待辦、數字表一律用人名；推定不出來的保留 SPEAKER_xx。品質註記裡寫一句推定依據。
   名單沒有的人不要憑空加；名單只有一人時不要硬分。
9. 輸入若附「已確認詞彙表」：一律用表裡的正確寫法，不要列進「未確認專名」。"""


def _claude(system: str, user_text: str, model: str | None = None, timeout: float = 900,
            cwd: Path | None = None) -> str:
    # --setting-sources ""：不載入任何 settings／CLAUDE.md／hooks（實測 2026-09-14：不加會被 hook 注入的提醒帶偏；
    # 改用 --bare 則讀不到登入狀態）。--tools ""：純文字進出，不讓模型去讀檔或跑指令。
    cmd = [
        config.CLAUDE_BIN, "-p",
        "--output-format", "text",
        "--no-session-persistence",
        "--setting-sources", "",
        "--tools", "",
        "--system-prompt", system,
    ]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=user_text, capture_output=True, text=True, timeout=timeout,
                          cwd=str(cwd) if cwd else "/private/tmp")
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()
        raise RuntimeError(f"claude -p 失敗（rc={proc.returncode}）：{err or out[:300]}")
    if "Not logged in" in out:
        raise RuntimeError("claude CLI 未登入：先在終端機跑一次 `claude` 並 /login")
    return out


def _extract_json_array(text: str) -> list:
    m = re.search(r"```json\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("回覆裡找不到 JSON 陣列")
        raw = text[start : end + 1]
    return json.loads(raw)


def build_entities(by_minute: str, plain_text: str, model: str | None = None,
                   glossary_md: str | None = None) -> tuple[str, list[dict]]:
    """回 (entities.md 內容, 候選 list)。出現次數在本機精算，不信模型的數字。"""
    user = f"## 已確認詞彙表（不用再列）\n\n{glossary_md}\n\n## 逐字稿（逐分鐘）\n\n{by_minute}" if glossary_md else by_minute
    reply = _claude(ENTITY_SYSTEM, user, model=model)
    try:
        items = _extract_json_array(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"專名候選表解析失敗：{exc}\n回覆前 500 字：{reply[:500]}") from exc

    rows = []
    for it in items:
        cand = str(it.get("candidate", "")).strip()
        if not cand:
            continue
        variants = [v.strip() for v in re.split(r"[／/]", cand) if v.strip()]
        count = sum(plain_text.count(v) for v in variants)
        rows.append({
            "candidate": cand,
            "type": str(it.get("type", "")).strip(),
            "likely": str(it.get("likely", "")).strip() or "未確認",
            "reason": str(it.get("reason", "")).strip(),
            "timestamps": [str(t) for t in (it.get("timestamps") or [])][:3],
            "count": count,
        })
    rows.sort(key=lambda r: -r["count"])

    lines = [
        "# 專名候選表（請確認後再產摘要）",
        "",
        "填法：在最後一欄「確認正解」填正確寫法；留空＝未確認，摘要會沿用逐字稿原字並列入「未確認專名」。",
        "填完跑：`meeting-local summarize <這個資料夾>`",
        "",
        "| # | 候選（逐字稿原字） | 類型 | 出現次數 | 模型推測 | 依據 | 時間戳 | 確認正解（請填） |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        ts = "、".join(r["timestamps"])
        lines.append(f"| {i} | {r['candidate']} | {r['type']} | {r['count']} | {r['likely']} | {r['reason']} | {ts} |  |")
    if not rows:
        lines.append("| – | （模型沒有列出任何候選） | | | | | |  |")
    return "\n".join(lines) + "\n", rows


_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_UNSAFE = re.compile(r"[\\/／＼:*?\"<>|\s　]+")


def safe_title(title: str, max_len: int = 24) -> str:
    """標題變成檔名可用的片段：去掉路徑符號與空白，截到 max_len 字。"""
    t = _UNSAFE.sub("", title).strip("-－.")
    return t[:max_len] or "會議"


def build_summary_input(by_minute: str, entities_md: str, attendees: list[str] | None = None,
                        glossary_md: str | None = None) -> str:
    parts = []
    if attendees:
        parts.append("## 與會者\n\n" + "、".join(attendees))
    if glossary_md:
        parts.append("## 已確認詞彙表\n\n" + glossary_md)
    parts.append(f"## 專名確認表\n\n{entities_md}")
    parts.append(f"## 逐字稿（逐分鐘）\n\n{by_minute}")
    return "\n\n".join(parts)


def build_summary(by_minute: str, entities_md: str, source: str, model: str | None = None,
                  meeting_time: str | None = None, attendees: list[str] | None = None,
                  glossary_md: str | None = None) -> tuple[str, str]:
    """回 (summary.md 內容, 模型決定的標題)。第一行標題會加上會議時間戳。"""
    user = build_summary_input(by_minute, entities_md, attendees, glossary_md)
    reply = _claude(SUMMARY_SYSTEM, user, model=model).strip()
    m = _TITLE_RE.search(reply)
    if m and reply.lstrip().startswith("#"):
        title = m.group(1).strip().lstrip("#").strip()
        body = reply[m.end():].lstrip("\n")
    else:
        title = "會議摘要"
        body = reply
    stamp = meeting_time or time.strftime("%Y-%m-%d %H:%M")
    who = f"｜與會者：{'、'.join(attendees)}" if attendees else ""
    header = (
        f"<!-- 來源：{source}｜產生時間：{time.strftime('%Y-%m-%d %H:%M')}｜"
        f"摘要模型：claude CLI（{model or 'default'}）｜STT：whisper.cpp large-v3-turbo（本機）{who} -->\n\n"
        f"# {title}（{stamp}）\n\n"
    )
    return header + body.rstrip() + "\n", title


def plain_text_of(segments: list[Segment]) -> str:
    return "\n".join(f"[{fmt_clock(s.start)}] {s.text}" for s in segments if s.flag != "hallucination")
