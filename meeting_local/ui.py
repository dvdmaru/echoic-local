"""最簡單的錄音視窗：來源三選一、開始／停止、經過時間、即時波形與音量、錄完一鍵轉逐字稿＋摘要、新會議。

只用 Python 內建 tkinter，不多裝東西。波形來源＝ffmpeg 同一路錄進檔案的訊號（看到的就是存下來的）。
"""
from __future__ import annotations

import array
import contextlib
import io
import math
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__, config, settings
from .audio import build_record_cmd, describe_devices, input_volume_note, list_audio_devices, pick_blackhole, pick_microphone, probe
from .outputs import update_run_json
from .summarize import safe_title

CHUNK_BYTES = 1600  # 50 ms @ 16 kHz s16le mono
HISTORY = 480       # 畫面上保留 480 個 50 ms 點 = 24 秒
QUIET_WINDOW = 40   # 「幾乎沒有聲音」看最近 2 秒的最大值，不看單一 50 ms（講話句間空隙會誤報）
QUIET_DB = -50.0


def _rms_db(chunk: bytes) -> tuple[float, float]:
    samples = array.array("h", chunk)
    if not samples:
        return -90.0, -90.0
    acc = 0
    peak = 0
    for v in samples:
        acc += v * v
        if abs(v) > peak:
            peak = abs(v)
    rms = math.sqrt(acc / len(samples)) / 32768.0
    return (20 * math.log10(rms) if rms > 0 else -90.0), (20 * math.log10(peak / 32768.0) if peak else -90.0)


class RecorderUI:
    def __init__(self, root: tk.Tk, out_root: Path):
        self.root = root
        self.out_root = out_root
        self.proc: subprocess.Popen | None = None
        self.reader: threading.Thread | None = None
        self.levels: deque[tuple[float, float]] = deque(maxlen=HISTORY)
        self.started_at: float | None = None
        self.job: Path | None = None
        self.busy = False
        self._ffmpeg_log = None
        self._rec_info: dict = {}
        self._pow_acc = 0.0   # 整場：各 50 ms 窗 RMS 功率累加（算整場平均 dB 用）
        self._pow_n = 0
        self._peak_db = -90.0

        root.title(f"{config.APP_NAME} {__version__}")
        root.geometry("780x640")
        root.minsize(640, 520)

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        devices = list_audio_devices()
        mic = pick_microphone(devices)
        bh = pick_blackhole(devices)
        self.has_mic = mic is not None
        self.has_bh = bh is not None
        dev_text = f"麥克風：{mic[1] if mic else '找不到'}　｜　系統音（BlackHole）：{bh[1] if bh else '未安裝'}"
        ttk.Label(frm, text=dev_text).pack(anchor="w")

        # 來源三選一
        src_row = ttk.Frame(frm)
        src_row.pack(anchor="w", pady=(4, 6))
        ttk.Label(src_row, text="錄音來源：").pack(side="left")
        self.source_var = tk.StringVar(value="both" if (self.has_bh and self.has_mic) else ("mic" if self.has_mic else "system"))
        for value, label, ok in (("mic", "只錄麥克風（實體會議）", self.has_mic),
                                 ("system", "只錄系統音（YouTube／對方聲音，不收現場）", self.has_bh),
                                 ("both", "兩者都錄（線上會議）", self.has_bh and self.has_mic)):
            rb = ttk.Radiobutton(src_row, text=label, value=value, variable=self.source_var)
            rb.pack(side="left", padx=(0, 10))
            if not ok:
                rb.state(["disabled"])

        # 會議名稱（選填）＋新會議
        name_row = ttk.Frame(frm)
        name_row.pack(fill="x", pady=(0, 6))
        ttk.Label(name_row, text="會議名稱（選填，留空＝摘要後由模型取名）：").pack(side="left")
        self.name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.name_var, width=28).pack(side="left", padx=(4, 8))
        self.btn_new = ttk.Button(name_row, text="＋ 新會議", command=self.new_meeting)
        self.btn_new.pack(side="left")

        # 與會者（選填）：填了就照人數做說話人分離，摘要依內容推定誰說的
        att_row = ttk.Frame(frm)
        att_row.pack(fill="x", pady=(0, 6))
        ttk.Label(att_row, text="與會者（選填，逗號分隔；填了就照人數分離、摘要用人名）：").pack(side="left")
        self.attendees_var = tk.StringVar()
        ttk.Entry(att_row, textvariable=self.attendees_var, width=36).pack(side="left", padx=(4, 0))

        # 自動摘要開關：會用到使用者自己的 Claude 額度，預設關、記住選擇
        sum_row = ttk.Frame(frm)
        sum_row.pack(fill="x", pady=(0, 6))
        self.has_claude = config.claude_available()
        self.auto_summary_var = tk.BooleanVar(value=settings.auto_summary() and self.has_claude)
        cb = ttk.Checkbutton(sum_row, text="轉完逐字稿後，自動用 Claude 產生摘要",
                             variable=self.auto_summary_var, command=self._toggle_auto_summary)
        cb.pack(anchor="w")
        note = settings.SUMMARY_COST_NOTE if self.has_claude else (
            "沒有偵測到 Claude Code，所以只會產出逐字稿。想要摘要：安裝 Claude Code 並登入，重新開啟這個 App。")
        if not self.has_claude:
            cb.state(["disabled"])
        ttk.Label(sum_row, text=note, wraplength=720, foreground="#555").pack(anchor="w", padx=(22, 0))

        row = ttk.Frame(frm)
        row.pack(fill="x")
        self.btn_start = ttk.Button(row, text="● 開始錄音", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row, text="■ 停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.lbl_time = ttk.Label(row, text="00:00:00", font=("Menlo", 20))
        self.lbl_time.pack(side="left", padx=(20, 0))
        self.lbl_db = ttk.Label(row, text="－ dB", font=("Menlo", 14))
        self.lbl_db.pack(side="right")

        self.canvas = tk.Canvas(frm, height=180, bg="#111418", highlightthickness=0)
        self.canvas.pack(fill="x", pady=(10, 6))

        self.lbl_status = ttk.Label(frm, text="待命。選來源、按「開始錄音」；講話時波形會動；停止後可直接轉逐字稿。", wraplength=720)
        self.lbl_status.pack(anchor="w")

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(8, 4))
        self.btn_setup = ttk.Button(row2, text="下載語音辨識模型（首次一次，約 1.6 GB）", command=self.download_models)
        self.btn_setup.pack(side="left")
        self.btn_all = ttk.Button(row2, text=self._all_label(), command=self.run_all, state="disabled")
        self.btn_all.pack(side="left", padx=(8, 0))
        self.btn_summary = ttk.Button(row2, text="產生這場摘要（Claude）", command=self.run_summary, state="disabled")
        self.btn_summary.pack(side="left", padx=(8, 0))
        self.btn_open = ttk.Button(row2, text="開啟資料夾", command=self.open_folder, state="disabled")
        self.btn_open.pack(side="left", padx=(8, 0))

        self.log = tk.Text(frm, height=8, font=("Menlo", 11), bg="#f6f6f6")
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.configure(state="disabled")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(0, self._startup_health)
        self._tick()

    # ---------------------------------------------------------- helpers
    def say(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, text: str) -> None:
        self.lbl_status.configure(text=text)

    def _startup_health(self) -> None:
        """把封裝版缺少的元件說清楚，避免使用者錄完才知道不能轉錄。"""
        missing = []
        if not Path(config.WHISPER_SERVER).exists():
            missing.append("內建語音辨識引擎")
        if not Path(config.WHISPER_MODEL).exists():
            missing.append("語音辨識模型")
        if not self.has_claude:
            self.say("ℹ️ 沒有偵測到 Claude Code：可以錄音和轉逐字稿，只是不會產生摘要。")
        if missing:
            self.set_status("⚠️ 初次設定尚未完成：" + "、".join(missing) + "。")
            self.say("初次設定：" + "、".join(missing))
        else:
            self.btn_setup.configure(state="disabled")
            self.say("✅ 語音辨識引擎與模型已就緒。")

    def download_models(self) -> None:
        if self.busy:
            return
        if not Path(config.WHISPER_SERVER).exists():
            messagebox.showerror("缺少語音辨識引擎", f"這個 App 的內建引擎不存在或已損毀，請重新安裝{config.APP_NAME}。")
            return
        if not messagebox.askyesno(
            "下載語音辨識模型",
            "將從 Hugging Face 官方下載約 1.6 GB 的 Whisper 模型與小型 VAD 模型，下載後比對官方 SHA256。\n"
            f"模型存在 {config.SHARED_MODELS_DIR}（和「看懂」共用，裝過看懂就不用再下載）。\n"
            "下載模型不會上傳任何會議內容。\n\n現在下載嗎？",
        ):
            return
        self.busy = True
        self.btn_setup.configure(state="disabled")
        self.set_status("⏳ 正在下載語音辨識模型，請保持網路連線…")

        def worker() -> None:
            def progress(text: str) -> None:
                self.root.after(0, self.say, text)
            try:
                config.download_whisper_models(progress)
            except RuntimeError as exc:
                self.root.after(0, self._models_done, False, str(exc))
            else:
                self.root.after(0, self._models_done, True, "")

        threading.Thread(target=worker, daemon=True).start()

    def _models_done(self, ok: bool, detail: str) -> None:
        self.busy = False
        if ok:
            self.set_status("✅ 語音辨識模型已下載完成，可以開始錄音。")
            self.say("✅ 語音辨識模型已就緒。")
        else:
            self.btn_setup.configure(state="normal")
            self.set_status("❌ 模型下載失敗。請檢查網路後重試。")
            self.say("❌ " + detail)

    def new_meeting(self) -> None:
        """清掉上一場的狀態，準備錄下一場（錄音中不可按）。"""
        if self.proc is not None or self.busy:
            return
        self.job = None
        self.levels.clear()
        self.started_at = None
        self.name_var.set("")
        self.attendees_var.set("")
        self.lbl_time.configure(text="00:00:00")
        self.lbl_db.configure(text="－ dB", foreground="black")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.btn_all.configure(state="disabled")
        self.btn_summary.configure(state="disabled")
        self.btn_open.configure(state="disabled")
        self.set_status("新會議。選來源、（可選）填名稱，按「開始錄音」。")

    # ---------------------------------------------------------- recording
    def start(self) -> None:
        if self.proc is not None or self.busy:
            return
        stamp = time.strftime("%Y-%m-%d-%H%M")
        name = safe_title(self.name_var.get().strip()) if self.name_var.get().strip() else ""
        self.job = self.out_root / (f"{stamp}-{name}" if name else stamp)
        wav = self.job / "audio.wav"
        try:
            cmd, info = build_record_cmd(wav, pipe_pcm=True, quiet=True, source=self.source_var.get())
        except (RuntimeError, ValueError) as exc:
            self.set_status(f"❌ {exc}")
            return
        if info["warning"]:
            self.say("⚠️ " + info["warning"])
        vol = info.get("input_volume")
        note = input_volume_note(info)
        if note:
            self.say(note)
        self._rec_info = info
        # ffmpeg 的 stderr 寫到工作資料夾的 ffmpeg.log：出事看得到，也不會塞管線。第一行記裝置，事後查得到用哪支麥克風。
        self._ffmpeg_log = open(self.job / "ffmpeg.log", "ab", buffering=0)
        self._ffmpeg_log.write(
            f"# {time.strftime('%Y-%m-%d %H:%M:%S')} mode={info['mode']} {describe_devices(info)} input_volume={vol}\n".encode()
        )
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._ffmpeg_log)
        self.levels.clear()
        self._pow_acc, self._pow_n, self._peak_db = 0.0, 0, -90.0
        self.started_at = time.time()
        self.reader = threading.Thread(target=self._read_pcm, daemon=True)
        self.reader.start()
        mode = {"mic": "只錄麥克風", "system": "只錄系統音", "mic+system": "麥克風＋系統音"}[info["mode"]]
        self.set_status(f"🔴 錄音中（{mode}）→ {wav}")
        self.say(f"開始錄音（{mode}；{describe_devices(info)}）：{wav}")
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_new.configure(state="disabled")
        self.btn_all.configure(state="disabled")
        self.btn_open.configure(state="disabled")

    def _read_pcm(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            r_db, p_db = _rms_db(chunk)
            self.levels.append((r_db, p_db))
            self._pow_acc += 10 ** (r_db / 10)
            self._pow_n += 1
            if p_db > self._peak_db:
                self._peak_db = p_db

    def stop(self) -> None:
        proc = self.proc
        if proc is None:
            return
        self.set_status("停止中，等 ffmpeg 寫完檔頭…")
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                    proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=5)
        else:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        self.proc = None
        if self._ffmpeg_log:
            self._ffmpeg_log.close()
            self._ffmpeg_log = None
        if proc.returncode not in (0, None, 255):
            tail = ""
            try:
                tail = (self.job / "ffmpeg.log").read_text(errors="replace").strip().splitlines()[-1]
            except (OSError, IndexError):
                pass
            self.say(f"ffmpeg exit {proc.returncode}：{tail}")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_new.configure(state="normal")
        wav = self.job / "audio.wav" if self.job else None
        if wav and wav.exists() and wav.stat().st_size > 1000:
            try:
                info = probe(wav)
                wall = (time.time() - self.started_at) if self.started_at else 0
                shortfall = wall - info["duration"]
                # 開裝置固定吃掉約 0.5–1.5 秒，短錄音別誤報；超過 2 秒且超過 5% 才算掉音訊
                note = "" if shortfall <= max(2.0, 0.05 * wall) else f"（⚠️ 牆上時間 {wall:.0f} 秒，檔案只有 {info['duration']:.0f} 秒，有掉音訊）"
                mean_db = round(10 * math.log10(self._pow_acc / self._pow_n), 1) if self._pow_n else None
                peak_db = round(self._peak_db, 1) if self._pow_n else None
                lvl = f"；平均 {mean_db} dB／峰值 {peak_db} dB" if mean_db is not None else ""
                self.set_status(f"✅ 錄音完成：{info['duration']:.1f} 秒{note}{lvl} → {wav}")
                self.say(f"錄音完成：{info['duration']:.1f} 秒{note}{lvl}，{wav}")
                if mean_db is not None and mean_db < config.LOW_LEVEL_DB:
                    self.say(f"⚠️ 這場偏小聲（平均 {mean_db} dB，低於 {config.LOW_LEVEL_DB:.0f}）。轉錄會先正規化；"
                             "輸入音量已自動拉高，想更好只能讓麥克風靠近講話的人（外接麥克風）。")
                rec = {"mode": self._rec_info.get("mode"), "mic": self._rec_info.get("mic"),
                       "blackhole": self._rec_info.get("blackhole"), "input_volume": self._rec_info.get("input_volume"),
                       "wall_seconds": round(wall, 1), "duration": info["duration"],
                       "mean_db": mean_db, "peak_db": peak_db, "source_choice": self.source_var.get()}
                try:
                    update_run_json(self.job / "run.json", job=self.job.name, record=rec, tool_version=__version__)
                except OSError as exc:
                    self.say(f"run.json 寫入失敗：{exc}")
            except RuntimeError as exc:
                self.set_status(f"錄音檔存了但 ffprobe 讀不到：{exc}")
            self.btn_all.configure(state="normal")
            self.btn_open.configure(state="normal")
        else:
            self.set_status("❌ 沒有錄到東西（檔案不存在或幾乎是空的）。檢查麥克風權限，看資料夾裡的 ffmpeg.log。")

    # ---------------------------------------------------------- pipeline
    def _all_label(self) -> str:
        if self.auto_summary_var.get():
            return "轉逐字稿＋摘要（會叫 whisper 與 Claude，數分鐘）"
        return "轉逐字稿（本機 whisper，數分鐘）"

    def _toggle_auto_summary(self) -> None:
        try:
            settings.save({"auto_summary": bool(self.auto_summary_var.get())})
        except OSError as exc:
            self.say(f"⚠️ 設定沒存起來：{exc}")
        self.btn_all.configure(text=self._all_label())

    def _has_transcript(self) -> bool:
        return self.job is not None and (self.job / "transcript-by-minute.txt").exists()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_all, self.btn_start, self.btn_new):
            b.configure(state=state)
        can_sum = not busy and self.has_claude and self._has_transcript()
        self.btn_summary.configure(state="normal" if can_sum else "disabled")

    def _run_cli(self, argv: list[str]) -> None:
        def worker() -> None:
            from .cli import main as cli_main

            class UILog(io.TextIOBase):
                def write(_self, text: str) -> int:
                    if text.strip():
                        self.root.after(0, self._pipeline_line, text)
                    return len(text)

            stream = UILog()
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                rc = cli_main(argv)
            self.root.after(0, self._all_done, rc, argv[0])

        threading.Thread(target=worker, daemon=True).start()

    def _common_argv(self) -> list[str]:
        argv = []
        if self.name_var.get().strip():
            argv.append("--no-rename")  # 使用者自己取的名字就保留，不用模型的標題改名
        attendees = self.attendees_var.get().strip()
        if attendees:
            argv += ["--attendees", attendees]
        return argv

    def run_all(self) -> None:
        if self.job is None or self.busy:
            return
        want = bool(self.auto_summary_var.get())
        self._set_busy(True)
        self.set_status("⏳ 轉逐字稿＋說話人分離" + ("＋專名表＋摘要" if want else "") + "…（下面會印進度；建議先關 Chrome）")
        self._run_cli(["all", str(self.job), "--summary" if want else "--no-summary", *self._common_argv()])

    def run_summary(self) -> None:
        if self.job is None or self.busy or not self._has_transcript():
            return
        self._set_busy(True)
        self.set_status("⏳ 用 Claude 產生專名表與摘要…")
        self._run_cli(["summarize", str(self.job), *self._common_argv()])

    def _pipeline_line(self, text: str) -> None:
        self.say(text)
        m = re.search(r"資料夾改名 → (.+?)\s*$", text)
        if m:
            self.job = Path(m.group(1))

    def _all_done(self, rc: int, step: str = "all") -> None:
        from .cli import SUMMARY_FAILED

        self._set_busy(False)
        has_summary = self.job is not None and (self.job / "summary.md").exists()
        if rc == 0 and has_summary:
            self.set_status(f"✅ 完成：{self.job}。填好 entities.md 的「確認正解」後可按「產生這場摘要」重做；按「＋ 新會議」錄下一場。")
        elif rc == 0:
            self.set_status(f"✅ 逐字稿完成：{self.job}。要摘要就按「產生這場摘要」；按「＋ 新會議」錄下一場。")
        elif rc == SUMMARY_FAILED:
            self.set_status("⚠️ 逐字稿已完成，但摘要沒做成（看上面的訊息）。可以稍後再按「產生這場摘要」。")
        elif step == "summarize":
            self.set_status(f"❌ 摘要失敗（exit {rc}），逐字稿不受影響。看上面的訊息。")
        else:
            self.set_status(f"❌ 管線失敗（exit {rc}），看上面的訊息。")

    def open_folder(self) -> None:
        if self.job:
            subprocess.Popen(["open", str(self.job)])

    # ---------------------------------------------------------- drawing
    def _tick(self) -> None:
        if self.proc is not None and self.started_at is not None:
            el = int(time.time() - self.started_at)
            self.lbl_time.configure(text=f"{el // 3600:02d}:{(el % 3600) // 60:02d}:{el % 60:02d}")
            if self.proc.poll() is not None:
                self.say(f"❌ ffmpeg 意外結束（exit {self.proc.returncode}）")
                self.stop()
        self._draw()
        self.root.after(50, self._tick)

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 10)
        h = c.winfo_height()
        mid = h / 2
        levels = list(self.levels)
        if not levels:
            c.create_line(0, mid, w, mid, fill="#334")
            return
        step = w / HISTORY
        x0 = w - len(levels) * step
        for i, (r_db, p_db) in enumerate(levels):
            x = x0 + i * step
            amp = max(0.0, (r_db + 60) / 60)  # -60 dB → 0，0 dB → 1
            pk = max(0.0, (p_db + 60) / 60)
            c.create_line(x, mid - pk * mid, x, mid + pk * mid, fill="#2b4a6b")
            c.create_line(x, mid - amp * mid, x, mid + amp * mid, fill="#4fc3f7", width=max(1, step))
        recent = levels[-QUIET_WINDOW:]
        rms_recent = max(r for r, _ in recent)     # 最近 2 秒最大 RMS：句間空隙不會誤報沒聲音
        peak_recent = max(p for _, p in recent)
        color = "#e57373" if peak_recent > -1.0 else ("#81c784" if rms_recent > -45 else "#ffb74d")
        self.lbl_db.configure(text=f"{rms_recent:5.1f} dB", foreground=color)
        if self.proc is not None:
            if peak_recent > -1.0:
                c.create_text(w / 2, 14, text="爆音（太大聲）", fill="#e57373", font=("Helvetica", 11))
            elif rms_recent < QUIET_DB:
                c.create_text(w / 2, 14, text="最近 2 秒幾乎沒有聲音進來", fill="#ffb74d", font=("Helvetica", 11))
            elif len(levels) >= HISTORY // 2:
                # 24 秒內有聲音的窗平均：低於門檻（-40）＝比 10/4 出事那場還小聲；輸入音量開錄時已自動拉高，能改的只剩麥克風位置
                voiced = [r for r, _ in levels if r > -60]
                if voiced:
                    avg = 10 * math.log10(sum(10 ** (r / 10) for r in voiced) / len(voiced))
                    if avg < config.LOW_LEVEL_DB:
                        c.create_text(w / 2, 14, text=f"音量偏低（24 秒平均 {avg:.0f} dB）：正規化會補，想更好請讓麥克風靠近講話的人",
                                      fill="#ffb74d", font=("Helvetica", 11))

    def on_close(self) -> None:
        if self.proc is not None:
            self.stop()
        self.root.destroy()


def main(out_root: Path = config.OUT_ROOT) -> int:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua")
    except tk.TclError:
        pass
    RecorderUI(root, out_root)
    root.mainloop()
    return 0
