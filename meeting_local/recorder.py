"""錄音控制（不綁任何介面）：ffmpeg 同一路寫檔＋吐 PCM，算即時音量；停止後比對牆上時間、寫 run.json。

網頁介面（webapp.py）用它；舊的 tkinter 視窗（ui.py）保留自己的實作不動。
"""
from __future__ import annotations

import array
import math
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from . import __version__, config
from .audio import build_record_cmd, describe_devices, input_volume_note, probe
from .outputs import update_run_json

CHUNK_BYTES = 1600  # 50 ms @ 16 kHz s16le mono
HISTORY = 480       # 保留 24 秒的音量點


def rms_db(chunk: bytes) -> tuple[float, float]:
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


class Recorder:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.job: Path | None = None
        self.started_at: float | None = None
        self.levels: deque[float] = deque(maxlen=HISTORY)
        self.info: dict = {}
        self.source = "mic"
        self._log = None
        self._reader: threading.Thread | None = None
        self._pow_acc = 0.0
        self._pow_n = 0
        self._peak = -90.0

    @property
    def recording(self) -> bool:
        return self.proc is not None

    def elapsed(self) -> float:
        return (time.time() - self.started_at) if (self.started_at and self.proc) else 0.0

    def start(self, job: Path, source: str) -> list[str]:
        """開錄。回傳要給使用者看的提醒（找不到 BlackHole、輸入音量等）。"""
        if self.proc is not None:
            raise RuntimeError("已經在錄音了")
        wav = job / "audio.wav"
        cmd, info = build_record_cmd(wav, pipe_pcm=True, quiet=True, source=source)
        job.mkdir(parents=True, exist_ok=True)
        notes = [n for n in (info.get("warning"), input_volume_note(info)) if n]
        self._log = open(job / "ffmpeg.log", "ab", buffering=0)
        self._log.write(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} mode={info['mode']} {describe_devices(info)} "
                        f"input_volume={info.get('input_volume')}\n".encode())
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log)
        self.job, self.info, self.source = job, info, source
        self.levels.clear()
        self._pow_acc, self._pow_n, self._peak = 0.0, 0, -90.0
        self.started_at = time.time()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        return notes

    def _read(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            r, p = rms_db(chunk)
            self.levels.append(r)
            self._pow_acc += 10 ** (r / 10)
            self._pow_n += 1
            self._peak = max(self._peak, p)

    def stop(self) -> dict:
        """停止並收尾。回傳 {ok, duration, note, mean_db, peak_db, message}。"""
        proc = self.proc
        if proc is None:
            return {"ok": False, "message": "沒有在錄音"}
        wall = time.time() - (self.started_at or time.time())
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
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:  # 收不到聲音（例如沒有麥克風權限）時 ffmpeg 可能不理 TERM
                    proc.kill()
                    proc.wait(timeout=5)
        self.proc = None
        if self._log:
            self._log.close()
            self._log = None
        job = self.job
        wav = job / "audio.wav" if job else None
        if not wav or not wav.exists() or wav.stat().st_size <= 1000:
            hint = "（整段都沒收到聲音：多半是 macOS 沒給麥克風權限，到 系統設定 → 隱私權與安全性 → 麥克風 打開）" if not self._pow_n else ""
            return {"ok": False, "message": f"沒有錄到東西（檔案不存在或幾乎是空的）{hint}。細節看資料夾裡的 ffmpeg.log。"}
        try:
            dur = probe(wav)["duration"]
        except RuntimeError as exc:
            return {"ok": True, "duration": None, "message": f"錄音檔存了但讀不到長度：{exc}"}
        short = wall - dur
        note = "" if short <= max(2.0, 0.05 * wall) else f"牆上時間 {wall:.0f} 秒，檔案只有 {dur:.0f} 秒，有掉音訊"
        mean_db = round(10 * math.log10(self._pow_acc / self._pow_n), 1) if self._pow_n else None
        peak_db = round(self._peak, 1) if self._pow_n else None
        rec = {"mode": self.info.get("mode"), "mic": self.info.get("mic"), "blackhole": self.info.get("blackhole"),
               "input_volume": self.info.get("input_volume"), "wall_seconds": round(wall, 1), "duration": dur,
               "mean_db": mean_db, "peak_db": peak_db, "source_choice": self.source}
        try:
            update_run_json(job / "run.json", job=job.name, record=rec, tool_version=__version__)
        except OSError:
            pass
        quiet = mean_db is not None and mean_db < config.LOW_LEVEL_DB
        return {"ok": True, "duration": dur, "note": note, "mean_db": mean_db, "peak_db": peak_db, "quiet": quiet,
                "message": f"錄音完成：{dur / 60:.1f} 分鐘" + (f"（⚠️ {note}）" if note else "")}
