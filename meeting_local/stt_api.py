"""線上語音辨識（使用者自選，預設不用）：任何 OpenAI 相容的 `/audio/transcriptions`。

為什麼有這條路：本機 whisper 轉一場長會議要佔滿 GPU 十幾二十分鐘，這段時間電腦很難做別的事。
線上服務把這段工作搬到別人的機器上，代價是**錄音會上傳到那個服務**——要不要相信它由使用者決定，
程式只負責講清楚（UI 選線上時會跳確認、每次轉錄的 log 第一行也會寫上傳到哪個網址）。

做法：
- 只講 OpenAI 的介面形狀（multipart：file、model、language、prompt、response_format=verbose_json），
  所以 OpenAI、Groq、自架的 faster-whisper／whisper.cpp 伺服器都能填。回來的 segments 自己組成 SRT，
  後面的去重、繁體、詞彙表、說話人分離跟本機路線完全同一條。
- 多數服務單檔上限 25 MB：先切成約 10 分鐘一段的 FLAC（16 kHz 單聲道約 0.5 MB／分鐘），
  切點挑目標時間前後 20 秒內最安靜的 0.5 秒，避免把一句話切成兩半。
- key 只放 0600 的檔案（或環境變數），用 stdin 交給 curl（`-H @-`），不會出現在 ps 看得到的參數裡，
  也不進 settings.json、run.json、log。
- 用 curl 不用 Python https：這台機器的 Python 缺 CA bundle（同 config.py 下載模型的理由）。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .srt import Segment

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "whisper-1"
CHUNK_SECONDS = 600.0
SEARCH_SECONDS = 20.0   # 切點在目標時間前後多少秒內找最安靜處
QUIET_WINDOW = 0.5      # 用多長的窗比安靜
UPLOAD_LIMIT = 25 * 1024 * 1024
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
RETRIES = 4

WARNING = (
    "線上語音辨識會把這場會議的錄音上傳到你填的服務（{host}），由對方的伺服器轉成文字。"
    "上傳之後怎麼保存、會不會拿去訓練，依那個服務的條款而定，這個 App 管不到。"
    "公司或客戶的會議，請先確認可以交給第三方處理。"
)


def host_of(base_url: str) -> str:
    return urlparse(base_url).netloc or base_url


def warning(base_url: str) -> str:
    return WARNING.format(host=host_of(base_url))


# ---------------------------------------------------------------- key
def load_key(path: Path | None = None) -> str | None:
    env = os.environ.get("MEETING_LOCAL_STT_API_KEY")
    if env and env.strip():
        return env.strip()
    path = path or config.STT_API_KEY_PATH
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def save_key(key: str, path: Path | None = None) -> Path:
    """寫成只有自己讀得到的檔（0600）；空字串＝刪掉。"""
    path = path or config.STT_API_KEY_PATH
    key = key.strip()
    if not key:
        path.unlink(missing_ok=True)
        return path
    if any(c in key for c in "\r\n"):
        raise ValueError("API key 不能有換行")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- chunks
def _quietest(samples, sr: int, lo: int, hi: int) -> int:
    """samples[lo:hi] 裡最安靜的 QUIET_WINDOW 窗的中點（樣本位置）。"""
    import numpy as np

    win = max(1, int(QUIET_WINDOW * sr))
    seg = np.asarray(samples[lo:hi], dtype=np.float32)
    if len(seg) <= win:
        return (lo + hi) // 2
    energy = np.convolve(seg * seg, np.ones(win, dtype=np.float32), mode="valid")
    return lo + int(np.argmin(energy)) + win // 2


def plan_chunks(duration: float, chunk_seconds: float = CHUNK_SECONDS, find_cut=None) -> list[tuple[float, float]]:
    """把 [0, duration] 切成約 chunk_seconds 一段。find_cut(target, lo, hi) 回實際切點（秒），沒給就切在目標上。
    最後一段太短（不到半段）就併進前一段，免得多打一次 API。"""
    if duration <= chunk_seconds * 1.5:
        return [(0.0, duration)]
    cuts = []
    t = chunk_seconds
    while duration - t > chunk_seconds * 0.5:
        lo, hi = max(0.0, t - SEARCH_SECONDS), min(duration, t + SEARCH_SECONDS)
        cuts.append(find_cut(t, lo, hi) if find_cut else t)
        t = cuts[-1] + chunk_seconds
    bounds = [0.0, *cuts, duration]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def plan_chunks_for(wav: Path, chunk_seconds: float = CHUNK_SECONDS) -> list[tuple[float, float]]:
    import soundfile as sf

    info = sf.info(str(wav))
    sr = info.samplerate

    def find_cut(target: float, lo: float, hi: float) -> float:
        start = int(lo * sr)
        frames = int((hi - lo) * sr)
        data, _ = sf.read(str(wav), start=start, frames=frames, dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        return (start + _quietest(mono, sr, 0, len(mono))) / sr

    return plan_chunks(info.frames / sr, chunk_seconds, find_cut)


def cut_flac(wav: Path, start: float, end: float, dst: Path) -> Path:
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
           "-i", str(wav), "-ac", "1", "-ar", "16000", "-c:a", "flac", str(dst)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    return dst


# ---------------------------------------------------------------- request
def curl_command(chunk: Path, base_url: str, model: str, language: str, prompt: str | None,
                 timeout: float) -> list[str]:
    """不含 key：key 走 stdin（`-H @-`）。-w 把 HTTP 狀態碼接在回應最後一行。"""
    cmd = [
        "curl", "-sS", "--max-time", str(int(timeout)), "-H", "@-",
        "-F", f"file=@{chunk}", "-F", f"model={model}", "-F", "response_format=verbose_json",
        "-F", "temperature=0", "-F", "timestamp_granularities[]=segment",
    ]
    if language:
        cmd += ["-F", f"language={language}"]
    if prompt:
        cmd += ["-F", f"prompt={prompt}"]
    cmd += ["-w", "\n%{http_code}", base_url.rstrip("/") + "/audio/transcriptions"]
    return cmd


class ApiError(RuntimeError):
    pass


def _short(body: str) -> str:
    """錯誤訊息只留服務自己的 message，不整包倒出來。"""
    try:
        obj = json.loads(body)
        err = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str):
            return err[:300]
    except (ValueError, AttributeError):
        pass
    return body.strip()[:300]


def request_chunk(chunk: Path, base_url: str, model: str, key: str, language: str, prompt: str | None,
                  timeout: float = 900, retries: int = RETRIES, sleep=time.sleep, run=subprocess.run) -> dict:
    cmd = curl_command(chunk, base_url, model, language, prompt, timeout)
    header = f"Authorization: Bearer {key}\n".encode()
    last = ""
    for attempt in range(retries + 1):
        proc = run(cmd, input=header, capture_output=True)
        out = proc.stdout.decode("utf-8", "replace")
        body, _, code = out.rpartition("\n")
        status = int(code) if code.strip().isdigit() else 0
        if proc.returncode == 0 and status == 200:
            try:
                return json.loads(body)
            except ValueError as exc:
                raise ApiError(f"服務回的不是 JSON（{host_of(base_url)}）：{body[:200]}") from exc
        last = (f"HTTP {status}：{_short(body)}" if status
                else f"連不上（curl rc={proc.returncode}）：{proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
        if status in (401, 403):
            raise ApiError(f"API key 被拒絕（{host_of(base_url)}，{last}）。到設定重填 key。")
        if status and status not in RETRY_STATUS:
            raise ApiError(f"線上語音辨識失敗（{host_of(base_url)}，{last}）")
        if attempt < retries:
            sleep(min(60, 5 * 2 ** attempt))
    raise ApiError(f"線上語音辨識重試 {retries} 次仍失敗（{host_of(base_url)}，{last}）")


def segments_from_response(obj: dict, offset: float, chunk_end: float | None = None) -> list[Segment]:
    segs = []
    for s in obj.get("segments") or []:
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        start = float(s.get("start") or 0) + offset
        end = float(s.get("end") or 0) + offset
        if chunk_end is not None:
            end = min(end, chunk_end)
        segs.append(Segment(start=start, end=max(start, end), text=text))
    if not segs and str(obj.get("text") or "").strip():
        # 沒給 segments 的服務（只回整段 text）：至少不要整段丟掉，時間軸就是這一整塊
        segs.append(Segment(start=offset, end=chunk_end or offset, text=str(obj["text"]).strip()))
    return segs


def transcribe(wav: Path, work_dir: Path, base_url: str, model: str, key: str, language: str,
               prompt: str | None, log=print, chunk_seconds: float = CHUNK_SECONDS) -> tuple[list[Segment], dict]:
    """回 (段落, 給 run.json 的資訊)。每段的原始回應存 work_dir/stt-api/，出事不必重傳。"""
    out = work_dir / "stt-api"
    out.mkdir(parents=True, exist_ok=True)
    chunks = plan_chunks_for(wav, chunk_seconds)
    segments: list[Segment] = []
    sent = 0
    t0 = time.time()
    for i, (start, end) in enumerate(chunks, 1):
        flac = cut_flac(wav, start, end, out / f"chunk-{i:02d}.flac")
        size = flac.stat().st_size
        if size > UPLOAD_LIMIT:
            raise ApiError(f"第 {i} 段 {size / 1e6:.1f} MB，超過多數服務的 25 MB 上限；把 MEETING_LOCAL_STT_CHUNK_SECONDS 調小再試")
        log(f"上傳第 {i}/{len(chunks)} 段（{start / 60:.1f}–{end / 60:.1f} 分，{size / 1e6:.1f} MB）→ {host_of(base_url)}")
        resp = request_chunk(flac, base_url, model, key, language, prompt)
        (out / f"chunk-{i:02d}.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
        flac.unlink(missing_ok=True)  # 音檔切片不留：原檔 audio.wav 還在
        segments.extend(segments_from_response(resp, start, end))
        sent += size
    info = {"engine": "api", "base_url_host": host_of(base_url), "model": model, "chunks": len(chunks),
            "uploaded_bytes": sent, "seconds": round(time.time() - t0), "local": False}
    return segments, info
