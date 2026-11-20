"""網頁介面（0.7.0 起的預設視窗）：pywebview 開一個 macOS 原生視窗（系統內建 WebKit），畫面是 web/ 底下的 HTML。

- 畫面要資料：JS 呼叫 `window.pywebview.api.<方法>()`（下面的 Api 類別），全部在本機。
- 網頁檔與錄音播放：只綁 127.0.0.1 的小伺服器，網址帶隨機 token、檢查 Host（擋其他網頁或 DNS rebinding 來讀會議）。
- 錄音／轉錄／摘要沿用既有模組（recorder、cli、library），這裡只做介面接線。
- 舊的 tkinter 視窗還在：`meeting-local ui --classic`，或沒有 pywebview 時自動退回。
"""
from __future__ import annotations

import contextlib
import functools
import io
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, config, library, mcp_server, settings, updater
from .recorder import Recorder
from .summarize import safe_title

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_FILES = {"index.html", "app.css", "app.js"}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PRESETS = {"OpenAI": ("https://api.openai.com/v1", "whisper-1"),
           "Groq": ("https://api.groq.com/openai/v1", "whisper-large-v3")}


def _expected(fn):
    """畫面那邊拿到 {"ok": False, "error": "..."} 而不是一個看不懂的例外。"""
    @functools.wraps(fn)
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": str(exc)}
    return wrap


class Api:
    def __init__(self, out_root: Path):
        self._out_root = out_root
        self._window = None
        self._rec = Recorder()
        self._lock = threading.Lock()
        self._log: list[str] = []
        self._busy: str = ""          # 正在跑的工作：pipeline／summary／models／update／project
        self._busy_job: str = ""
        self._last_done: dict | None = None
        self._release: dict | None = None
        self._progress: dict | None = None   # 下載進度：{"label", "done", "total"}，給畫面畫進度條
        self._rec_labels: dict = {}

    # ------------------------------------------------------------ 共用
    def _say(self, text: str) -> None:
        text = _ANSI.sub("", str(text))
        for line in text.split("\n"):
            line = line.rstrip("\r").rsplit("\r", 1)[-1]  # 進度列用 \r 覆寫，只留最後一段
            if line.strip():
                with self._lock:
                    self._log.append(line.rstrip())
                    if len(self._log) > 4000:
                        del self._log[:1000]

    def _bytes(self, label: str):
        """回一個 on_bytes(已下載, 總量) 回呼，把下載進度放進 poll 給畫面。"""
        def cb(done: int, total: int | None) -> None:
            self._progress = {"label": label, "done": int(done), "total": int(total) if total else None}
        return cb

    def _meetings(self) -> list[library.Meeting]:
        return library.load_meetings(self._out_root)

    def _get(self, mid: str) -> library.Meeting:
        m = library.find(self._meetings(), mid)
        if m is None:
            raise ValueError(f"找不到會議 {mid}")
        return m

    def _cats(self) -> list[str]:
        return settings.load()["categories"]

    def _start(self, name: str, job: str, fn) -> None:
        if self._busy:
            raise RuntimeError("另一件事還在跑，等它做完")
        self._busy, self._busy_job, self._last_done, self._progress = name, job, None, None

        def run():
            result = {"step": name, "job": job, "ok": False}
            try:
                result.update(fn() or {})
            except Exception as exc:  # noqa: BLE001 — 背景工作的錯誤要回報給畫面
                result["error"] = str(exc)
                self._say(f"❌ {exc}")
            finally:
                self._busy, self._busy_job, self._last_done, self._progress = "", "", result, None

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ 開機資料
    def bootstrap(self) -> dict:
        from . import stt_api
        from .audio import list_audio_devices, pick_blackhole, pick_microphone

        try:
            devices = list_audio_devices()
        except (RuntimeError, OSError):
            devices = []
        mic, bh = pick_microphone(devices), pick_blackhole(devices)
        missing = []
        if not Path(config.WHISPER_SERVER).exists():
            missing.append("engine")
        if not Path(config.WHISPER_MODEL).exists():
            missing.append("model")
        s = settings.load()
        return {
            "version": __version__, "out_root": str(self._out_root), "frozen": config.FROZEN,
            "has_claude": config.claude_available(), "missing": missing,
            "mic": mic[1] if mic else None, "blackhole": bh[1] if bh else None,
            "settings": self.get_settings(), "presets": PRESETS,
            "api_warning": stt_api.WARNING.format(host="你填的服務"),
            "update_due": updater.app_bundle() is not None and s["update_check"] and updater.due(s["update_checked_at"]),
        }

    def get_settings(self) -> dict:
        from . import stt_api

        s = settings.load()
        return {
            "auto_summary": s["auto_summary"], "stt_engine": s["stt_engine"], "local_speed": s["local_speed"],
            "stt_api_base_url": s["stt_api_base_url"], "stt_api_model": s["stt_api_model"],
            "stt_api_host": stt_api.host_of(s["stt_api_base_url"]), "has_api_key": stt_api.load_key() is not None,
            "update_check": s["update_check"], "categories": s["categories"],
            "mcp_enabled": s["mcp_enabled"], "mcp_transcripts": s["mcp_transcripts"], "mcp_scope": s["mcp_scope"],
        }

    @_expected
    def save_settings(self, values: dict) -> dict:
        allowed = {"auto_summary", "local_speed", "update_check", "categories", "mcp_enabled", "mcp_transcripts",
                   "mcp_scope", "stt_engine"}
        vals = {k: v for k, v in (values or {}).items() if k in allowed}
        if "categories" in vals and not settings._valid("categories", vals["categories"]):
            raise ValueError(f"分類欄位要 1～{settings.MAX_CATEGORIES} 個、不能重複")
        if vals.get("stt_engine") == "api":
            from . import stt_api
            if not stt_api.load_key():
                raise ValueError("還沒設定線上 API key")
        settings.save(vals)
        return {"ok": True, "settings": self.get_settings()}

    @_expected
    def save_api(self, url: str, model: str, key: str) -> dict:
        from . import stt_api

        url, model = (url or "").strip().rstrip("/"), (model or "").strip()
        if not url.startswith(("https://", "http://")) or not model:
            raise ValueError("網址要以 https:// 開頭，模型不能空白")
        if not (key or "").strip() and not stt_api.load_key():
            raise ValueError("第一次設定要填 API key")
        if (key or "").strip():
            stt_api.save_key(key)
        settings.save({"stt_api_base_url": url, "stt_api_model": model, "stt_engine": "api"})
        return {"ok": True, "settings": self.get_settings()}

    def api_warning(self, url: str) -> str:
        from . import stt_api
        return stt_api.warning(url or settings.load()["stt_api_base_url"])

    # ------------------------------------------------------------ 會議庫
    def tree(self) -> dict:
        ms = self._meetings()
        cats = self._cats()
        top, sub = cats[0], (cats[1] if len(cats) > 1 else None)
        groups: dict[str, dict] = {}
        for m in ms:
            v = m.labels.get(top, "")
            g = groups.setdefault(v, {"value": v, "count": 0, "children": {}})
            g["count"] += 1
            if sub and m.labels.get(sub):
                g["children"][m.labels[sub]] = g["children"].get(m.labels[sub], 0) + 1
        out = sorted((g for k, g in groups.items() if k), key=lambda g: (-g["count"], g["value"]))
        for g in out:
            g["children"] = [{"value": k, "count": n} for k, n in sorted(g["children"].items(), key=lambda kv: (-kv[1], kv[0]))]
        return {"categories": cats, "top": top, "sub": sub, "groups": out,
                "unlabeled": groups.get("", {}).get("count", 0), "total": len(ms),
                "open_todos": sum(1 for m in ms for t in m.todos if not t.done),
                "values": library.label_values(ms, cats)}

    def list_meetings(self, flt: dict | None = None) -> dict:
        flt = flt or {}
        labels = {k: v for k, v in (flt.get("labels") or {}).items() if v is not None}
        ms = library.filter_meetings(self._meetings(), labels, flt.get("date_from") or None, flt.get("date_to") or None)
        q = (flt.get("query") or "").strip()
        if q:
            res = library.search(ms, q, include_transcript=flt.get("transcript", True) is not False)
            items = [{**r["meeting"].brief(), "hits": r["hits"], "private": r["meeting"].private} for r in res]
        else:
            items = [{**m.brief(), "hits": [], "private": m.private} for m in ms]
        limit = int(flt.get("limit") or 500)
        return {"total": len(items), "meetings": items[:limit]}

    def open_todos(self) -> list[dict]:
        return [t.as_dict() | {"labels": m.labels} for m in self._meetings() for t in m.todos if not t.done]

    @_expected
    def get_meeting(self, mid: str) -> dict:
        m = self._get(mid)
        cats = self._cats()
        summary = library._strip_comments(m.summary_text()).strip()
        if summary.startswith("# "):  # 標題另外顯示
            summary = summary.split("\n", 1)[1] if "\n" in summary else ""
        meta = {}
        try:
            meta = json.loads((m.folder / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        stt = (meta.get("models_touched") or {}).get("stt") or {}
        ctx = library.project_context(self._out_root, self._meetings(), library.project_labels(m, cats), exclude_id=m.id)
        return {
            "ok": True, **m.brief(), "private": m.private, "folder": str(m.folder),
            "attendees": meta.get("attendees") or [],
            "summary_html": library.markdown_to_html(summary) if summary else "",
            "transcript": library.transcript_lines(m),
            "entities_html": library.read_file(m, "entities.md")["html"] if (m.folder / "entities.md").exists() else "",
            "files": library.list_files(m),
            "has_audio": (m.folder / "audio.wav").exists(),
            "stt": stt.get("engine") or "", "stt_host": stt.get("base_url_host") or "",
            "stt_failed": meta.get("stt_failed") or None,
            "language": meta.get("language") if meta.get("language") in config.LANGUAGES else config.WHISPER_LANGUAGE,
            "stt_partial": self._partial_loss(meta, stt),
            "context": ctx,
        }

    @staticmethod
    def _partial_loss(meta: dict, stt: dict) -> float | None:
        """線上辨識成功但有一段被幻覺迴圈吃掉（≥20%）→ 回比例，畫面提示可用本機重轉。
        舊的 run.json 沒有 hallucination_coverage，就用 hallucination_runs 現算。"""
        from .cli import STT_FAIL_COVERAGE, STT_PARTIAL_COVERAGE, hallucination_coverage

        if stt.get("engine") != "api" or meta.get("stt_failed"):
            return None
        cov = meta.get("hallucination_coverage")
        if cov is None:
            cov = hallucination_coverage(meta.get("hallucination_runs") or [], (meta.get("audio") or {}).get("duration") or 0)
        return round(cov, 3) if STT_PARTIAL_COVERAGE <= cov < STT_FAIL_COVERAGE else None

    @_expected
    def read_file(self, mid: str, name: str) -> dict:
        return {"ok": True, **library.read_file(self._get(mid), name)}

    @_expected
    def set_todo(self, mid: str, index: int, done: bool) -> dict:
        ok = library.set_todo_done(self._get(mid), int(index), bool(done))
        if ok:
            self._refresh(self._get(mid).folder)
        return {"ok": ok}

    @_expected
    def set_labels(self, ids: list[str], labels: dict, private=None) -> dict:
        ms = {m.id: m for m in self._meetings()}
        for mid in ids:
            if mid in ms:
                library.write_meta(ms[mid].folder, labels=labels, private=private)
        library.refresh_threads(self._out_root)
        for mid in ids:
            if mid in ms:
                library.refresh_threads(self._out_root, ms[mid].folder)
        from .index import write_index
        write_index(self._out_root)
        return {"ok": True}

    def _refresh(self, folder: Path) -> None:
        try:
            library.refresh_threads(self._out_root, folder)
            from .index import write_index
            write_index(self._out_root)
        except OSError:
            pass

    @_expected
    def project(self, labels: dict) -> dict:
        labels = {k: v for k, v in (labels or {}).items() if v}
        if not labels:
            raise ValueError("要選一個客戶或專案")
        ms = self._meetings()
        ctx = library.project_context(self._out_root, ms, labels)
        ctx["thread_file"] = str(library.thread_path(self._out_root, labels))
        ctx["with_summary"] = sum(1 for m in library.filter_meetings(ms, labels) if m.summary_path.exists())
        return {"ok": True, **ctx}

    @_expected
    def run_project_report(self, labels: dict) -> dict:
        labels = {k: v for k, v in (labels or {}).items() if v}
        ms = library.filter_meetings(self._meetings(), labels)

        def work():
            n = sum(1 for m in ms if m.summary_path.exists())
            self._say(f"🧠 請 Claude 讀「{library.thread_key(labels)}」{n} 場摘要整理進度…")
            report = library.project_report(labels, ms, model=config.CLAUDE_MODEL)
            meta = f"Claude 整理：{time.strftime('%Y-%m-%d %H:%M')}，讀了 {n} 場摘要"
            library.write_thread(self._out_root, labels, ms, ai_report=report, ai_meta=meta)
            self._say("✅ 進度整理完成")
            return {"ok": True}

        self._start("project", library.thread_key(labels), work)
        return {"ok": True}

    # ------------------------------------------------------------ 匯出／開檔
    def _ask_save(self, name: str, fmt: str) -> Path | None:
        import webview

        if self._window is None:
            return Path.home() / "Downloads" / name
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=str(Path.home() / "Downloads"),
                                             save_filename=name)
        if not res:
            return None
        return Path(res if isinstance(res, str) else res[0])

    @_expected
    def export(self, ids: list[str], fmt: str, include_transcript: bool, title: str = "") -> dict:
        all_ms = self._meetings()
        ms = [m for m in all_ms if m.id in set(ids or [])]
        if not ms:
            raise ValueError("沒有要匯出的會議")
        if len(ms) == 1:
            title, date = ms[0].title, ms[0].date
        else:
            title, date = title or "會議彙整", time.strftime("%Y-%m-%d")
        path = self._ask_save(library.export_name(title, date, fmt), fmt)
        if path is None:
            return {"ok": False, "cancelled": True}
        library.export(path, title, ms, fmt=fmt, include_transcript=bool(include_transcript))
        subprocess.Popen(["open", "-R", str(path)])
        return {"ok": True, "path": str(path)}

    @_expected
    def reveal(self, mid: str = "", name: str = "") -> dict:
        target = self._out_root
        if mid:
            m = self._get(mid)
            target = m.folder / name if name and (m.folder / name).is_file() else m.folder
        subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        return {"ok": True}

    @_expected
    def open_external(self, mid: str, name: str) -> dict:
        m = self._get(mid)
        path = (m.folder / name).resolve()
        if path.parent != m.folder.resolve():
            raise ValueError("檔名不對")
        subprocess.Popen(["open", str(path)])
        return {"ok": True}

    # ------------------------------------------------------------ 錄音
    def recording_context(self, labels: dict) -> dict:
        labels = {k: v for k, v in (labels or {}).items() if v}
        return library.project_context(self._out_root, self._meetings(), labels)

    @_expected
    def record_start(self, opts: dict) -> dict:
        if self._busy:
            raise RuntimeError("轉錄或摘要還在跑，等它做完再錄下一場")
        stamp = time.strftime("%Y-%m-%d-%H%M")
        name = (opts.get("name") or "").strip()
        job = self._out_root / (f"{stamp}-{safe_title(name)}" if name else stamp)
        notes = self._rec.start(job, opts.get("source") or "mic")
        self._rec_labels = {k: v for k, v in (opts.get("labels") or {}).items()}
        if any(v.strip() for v in self._rec_labels.values()):
            library.write_meta(job, labels=self._rec_labels)
        from .outputs import update_run_json
        attendees = (opts.get("attendees") or "").strip()
        if attendees:
            from .cli import parse_attendees
            update_run_json(job / "run.json", attendees=parse_attendees(attendees))
        if opts.get("language") in config.LANGUAGES:  # 轉錄時照這場選的語言（重轉可改）
            update_run_json(job / "run.json", language=opts["language"])
        for n in notes:
            self._say("⚠️ " + n)
        self._say(f"開始錄音：{job}")
        return {"ok": True, "job": job.name, "notes": notes}

    @_expected
    def record_stop(self) -> dict:
        job = self._rec.job
        res = self._rec.stop()
        self._say(res.get("message", ""))
        if res.get("quiet"):
            self._say(f"⚠️ 這場偏小聲（平均 {res['mean_db']} dB）。轉錄會先正規化；想更好只能讓麥克風靠近講話的人。")
        return {**res, "job": job.name if job else ""}

    @_expected
    def add_note(self, text: str) -> dict:
        from .cli import NOTES_NAME

        text = (text or "").strip()
        job = self._rec.job
        if not text or job is None:
            return {"ok": False}
        sec = int(self._rec.elapsed())
        stamp = f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
        path = job / NOTES_NAME
        new = not path.exists()
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("# 會議中手記\n\n")
            f.write(f"- [{stamp}] {text}\n")
        return {"ok": True, "t": stamp}

    def notes(self, mid: str) -> list[dict]:
        from .cli import NOTES_NAME

        m = library.find(self._meetings(), mid)
        folder = m.folder if m else self._out_root / mid
        try:
            text = (folder / NOTES_NAME).read_text(encoding="utf-8")
        except OSError:
            return []
        return [{"t": a, "text": b} for a, b in re.findall(r"^- \[(\d\d:\d\d:\d\d)\] (.*)$", text, re.M)]

    # ------------------------------------------------------------ 轉錄／摘要
    def _run_cli(self, argv: list[str]) -> int:
        from .cli import main as cli_main

        api = self

        class Sink(io.TextIOBase):
            def write(self, text: str) -> int:
                api._say(text)
                return len(text)

        with contextlib.redirect_stdout(Sink()), contextlib.redirect_stderr(Sink()):
            return cli_main(argv)

    def _resolve(self, job_name: str) -> str:
        """摘要後資料夾會改名成「時間戳-標題」；回傳現在的名稱。"""
        if (self._out_root / job_name).is_dir():
            return job_name
        stamp = job_name[:15]
        cands = sorted(p.name for p in self._out_root.iterdir() if p.is_dir() and p.name.startswith(stamp))
        return cands[-1] if cands else job_name

    @_expected
    def run_pipeline(self, mid: str, summary: bool | None = None, attendees: str = "", engine: str = "",
                     language: str = "") -> dict:
        from .cli import STT_FAILED, SUMMARY_FAILED

        s = settings.load()
        want = s["auto_summary"] if summary is None else bool(summary)
        # engine＝只這一場改用的引擎（「用本機重轉」按鈕）；不寫回設定檔
        eng = engine if engine in settings.ENGINES else s["stt_engine"]
        argv = ["all", str(self._out_root / mid), "--summary" if want else "--no-summary",
                "--engine", eng, "--speed", s["local_speed"]]
        if attendees.strip():
            argv += ["--attendees", attendees.strip()]
        if language in config.LANGUAGES:  # 「重轉」選的語言；會記進這場 run.json，下次沿用
            argv += ["--language", language]
        if not re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}$", mid):
            argv.append("--no-rename")  # 使用者自己取的名字就保留

        def work():
            rc = self._run_cli(argv)
            return {"ok": rc in (0, SUMMARY_FAILED), "rc": rc, "summary_failed": rc == SUMMARY_FAILED,
                    "stt_failed": rc == STT_FAILED, "new_id": self._resolve(mid)}

        self._start("pipeline", mid, work)
        return {"ok": True}

    @_expected
    def run_summary(self, mid: str) -> dict:
        argv = ["summarize", str(self._out_root / mid)]
        if not re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}$", mid[:15]) or len(mid) > 15:
            argv.append("--no-rename")

        def work():
            rc = self._run_cli(argv)
            return {"ok": rc == 0, "rc": rc, "new_id": self._resolve(mid)}

        self._start("summary", mid, work)
        return {"ok": True}

    # ------------------------------------------------------------ 模型／更新
    @_expected
    def download_models(self) -> dict:
        def work():
            config.download_whisper_models(self._say, on_bytes=self._bytes("下載語音辨識模型"))
            self._say("✅ 語音辨識模型已就緒")
            return {"ok": True}

        self._start("models", "", work)
        return {"ok": True}

    @_expected
    def check_update(self) -> dict:
        try:
            rel = updater.latest_release()
        finally:
            try:
                settings.save({"update_checked_at": time.time()})
            except OSError:
                pass
        if updater.newer(rel["version"], __version__):
            self._release = rel
            return {"ok": True, "newer": True, "version": rel["version"]}
        return {"ok": True, "newer": False, "version": __version__}

    @_expected
    def do_update(self) -> dict:
        bundle = updater.app_bundle()
        if bundle is None:
            raise RuntimeError("你是從原始碼執行：在專案資料夾跑 git pull 就是更新")
        if self._rec.recording:
            raise RuntimeError("錄音中，停止後再更新")
        rel = self._release or updater.latest_release()

        def work():
            new = updater.prepare(rel, bundle, log=self._say, on_bytes=self._bytes(f"下載 {rel['version']}"))
            self._progress = None
            self._say("✅ 新版準備好了，App 會關閉並自動重開。")
            updater.launch_swap(bundle, new)
            threading.Timer(0.8, lambda: self._window and self._window.destroy()).start()
            return {"ok": True}

        self._start("update", "", work)
        return {"ok": True}

    # ------------------------------------------------------------ AI 助理（MCP）
    def mcp_info(self) -> dict:
        path = mcp_server.access_log_path()
        recent = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-30:]:
                with contextlib.suppress(json.JSONDecodeError):
                    recent.append(json.loads(line))
        except OSError:
            pass
        return {"config_json": mcp_server.client_config_json(), "claude_code": mcp_server.claude_code_command(),
                "log_path": str(path), "recent": list(reversed(recent))}

    @_expected
    def copy_text(self, text: str) -> dict:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return {"ok": True}

    # ------------------------------------------------------------ 輪詢
    def poll(self, cursor: int = 0) -> dict:
        with self._lock:
            lines = self._log[cursor:] if cursor <= len(self._log) else self._log[-200:]
            new_cursor = len(self._log)
        rec = None
        if self._rec.recording:
            lv = list(self._rec.levels)[-160:]
            rec = {"elapsed": self._rec.elapsed(), "db": lv[-1] if lv else -90.0, "levels": lv,
                   "job": self._rec.job.name if self._rec.job else ""}
        done, self._last_done = self._last_done, None
        return {"cursor": new_cursor, "log": lines, "rec": rec, "busy": self._busy, "busy_job": self._busy_job,
                "progress": self._progress, "done": done}

    def js_error(self, msg: str) -> None:
        """畫面的 JS 錯誤：記進工作紀錄與 stderr，出事查得到。"""
        self._say(f"⚠️ 畫面錯誤：{str(msg)[:500]}")
        print(f"[webui] {str(msg)[:500]}", file=sys.stderr)

    def on_closing(self) -> None:
        if self._rec.recording:
            with contextlib.suppress(Exception):
                self._rec.stop()


# ---------------------------------------------------------------- 本機伺服器
def make_server(api: Api, token: str) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 不把請求印到終端機
            pass

        def _deny(self, code: int = 404) -> None:
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self._deny(403)
            parts = urllib.parse.urlsplit(self.path).path.split("/")
            if len(parts) < 2 or not secrets.compare_digest(parts[1], token):
                return self._deny(403)
            rest = [urllib.parse.unquote(p) for p in parts[2:]]
            if not rest or rest == [""]:
                rest = ["index.html"]
            if len(rest) == 1 and rest[0] in WEB_FILES:
                return self._send_file(WEB_DIR / rest[0])
            if len(rest) == 3 and rest[0] == "media":
                m = library.find(api._meetings(), rest[1])
                if m is None:
                    return self._deny()
                path = (m.folder / rest[2]).resolve()
                if path.parent != m.folder.resolve() or library.FILE_KINDS.get(path.suffix.lower()) != "audio":
                    return self._deny()
                return self._send_file(path, ranged=True)
            return self._deny()

        def _send_file(self, path: Path, ranged: bool = False) -> None:
            if not path.is_file():
                return self._deny()
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".js":
                ctype = "text/javascript"
            start, end = 0, size - 1
            rng = self.headers.get("Range") if ranged else None
            m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            length = end - start + 1
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes" if ranged else "none")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if path.name == "index.html":
                # 'unsafe-eval'：pywebview 把 Python 的回傳值用 eval 送回頁面，少了它所有 API 呼叫都不會回來（實測卡在「載入中」）。
                # 腳本來源仍只限本機這三個檔，外部腳本一律擋。
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
                                 "img-src 'self' data:; media-src 'self'; frame-src 'self' blob: data:; "
                                 "connect-src 'self'; font-src 'self' data:")
            self.end_headers()
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    left = length
                    while left > 0:
                        chunk = f.read(min(262144, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    return srv


def available() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def main(out_root: Path = config.OUT_ROOT) -> int:
    import webview

    out_root.mkdir(parents=True, exist_ok=True)
    api = Api(out_root)
    token = secrets.token_hex(16)
    srv = make_server(api, token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/{token}/"
    win = webview.create_window(f"{config.APP_NAME} {__version__}", url=url, js_api=api, width=1280, height=820,
                                min_size=(900, 600), background_color="#141d1b", text_select=True)
    api._window = win
    win.events.closing += api.on_closing
    webview.start(debug=bool(os.environ.get("MEETING_LOCAL_WEB_DEBUG")), private_mode=True)
    srv.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
