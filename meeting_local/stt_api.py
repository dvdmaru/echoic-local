"""線上語音辨識（使用者自選，預設不用）：任何 OpenAI 相容的 `/audio/transcriptions`。

為什麼有這條路：本機 whisper 轉一場長會議要佔滿 GPU 十幾二十分鐘，這段時間電腦很難做別的事。
線上服務把這段工作搬到別人的機器上，代價是**錄音會上傳到那個服務**——要不要相信它由使用者決定，
程式只負責講清楚（UI 選線上時會跳確認、每次轉錄的 log 第一行也會寫上傳到哪個網址）。

做法：
- 只講 OpenAI 的介面形狀（multipart：file、model、language、prompt、response_format=verbose_json），
  所以 OpenAI、Groq、自架的 faster-whisper／whisper.cpp 伺服器都能填。回來的 segments 自己組成 SRT，
  後面的去重、繁體、詞彙表、說話人分離跟本機路線完全同一條。
- 預設一句一句送（2026-11-22 起）：用音量切出有人講話的句子（最長 12 秒），一句一個請求、同時 4 句。
  某一句被服務亂回，只丟那幾秒；沒人講話的時間不送。舊做法（切成約 10 分鐘一段，切點挑最安靜處）
  11/19、11/22 兩次整段鬼打牆（一次丟掉 10 分鐘、一次整場），同兩份錄音改切句後都轉得出來。
  舊做法留作退路：MEETING_LOCAL_STT_SPLIT=chunk。
- key 只放 0600 的檔案（或環境變數），用 stdin 交給 curl（`-H @-`），不會出現在 ps 看得到的參數裡，
  也不進 settings.json、run.json、log。
- 用 curl 不用 Python https：這台機器的 Python 缺 CA bundle（同 config.py 下載模型的理由）。
"""
from __future__ import annotations

import json
import re
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
# 逐段檢查：一段（約 10 分鐘）裡有一半以上的時間是幻覺迴圈，就當這段壞了。
# 2026-11-22 實例：第 2 段整段回「整理&字幕由Amara.org社區提供」×77，那 10 分鐘正是會議主要內容，
# 整場算起來只有 38%（沒到整場失敗的 50%），摘要就漏了一大段也沒人提醒。
CHUNK_BAD = 0.5
RETRY_TEMPERATURE = 0.2  # 線上重試那一段時換一個溫度，同樣的請求再送一次多半回同樣的東西
# 壞段加起來不到全場這個比例，才逐段改用本機補；超過多半是會議語言選錯或只錄了麥克風，
# 交給整場失敗的流程（畫面提供「用本機重轉」），不在背景偷偷把整場改成本機。
LOCAL_REPAIR_MAX = 0.5

# ---- 一句一句送（預設）
SPLIT = os.environ.get("MEETING_LOCAL_STT_SPLIT", "sentence")  # sentence｜chunk
FRAME = 0.030           # 30 ms 一框算音量
PREROLL = 0.300         # 句首往前多留，免得切掉第一個字
END_SILENCE = 0.700     # 靜這麼久就收句
MAX_UTTERANCE = 12.0    # 一句最長幾秒（太長就硬切）
MIN_VOICED = 0.300      # 有聲音不到這麼久＝咳嗽、碰到桌子，不送
# 「有人講話」的門檻＝這份錄音的底噪 × 2（底噪＝非全零框音量的第 20 百分位）。送出前已做響度正規化，
# 固定門檻不適用：11/22 實驗 OwnVoice Meet 的 RMS 0.008 會把整場都當成有人講話。
# × 2 在兩場錄音只漏本機逐字稿 0.1% 的字（單字的「對」「OK」），× 3 漏 2%（含完整短句）。
NOISE_PERCENTILE = 20
NOISE_MULT = 2.0
WORKERS = 4             # 同時送幾句：11/22 兩場 325 次請求 0 錯誤
GAP_REPAIR_SECONDS = 60.0  # 連續這麼久都是幻覺，才改用本機補轉那一段

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


def cut_wav(wav: Path, start: float, end: float, dst: Path) -> Path:
    """本機補轉用：切出 16 kHz 單聲道 WAV（whisper-server 吃 WAV）。"""
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
           "-i", str(wav), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    return dst


# ---------------------------------------------------------------- request
def curl_command(chunk: Path, base_url: str, model: str, language: str, prompt: str | None,
                 timeout: float, temperature: float = 0.0) -> list[str]:
    """不含 key：key 走 stdin（`-H @-`）。-w 把 HTTP 狀態碼接在回應最後一行。"""
    cmd = [
        "curl", "-sS", "--max-time", str(int(timeout)), "-H", "@-",
        "-F", f"file=@{chunk}", "-F", f"model={model}", "-F", "response_format=verbose_json",
        "-F", f"temperature={temperature:g}", "-F", "timestamp_granularities[]=segment",
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
                  timeout: float = 900, retries: int = RETRIES, sleep=time.sleep, run=subprocess.run,
                  temperature: float = 0.0) -> dict:
    cmd = curl_command(chunk, base_url, model, language, prompt, timeout, temperature)
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


_PUNCT = re.compile(r"[\s，。、．,.!?！？：:；;「」『』（）()\[\]…\-—]+")


def is_prompt_echo(text: str, prompt: str, min_chunk: int = 4, threshold: float = 0.3) -> bool:
    """回應幾乎都是提示詞的片段＝服務把提示當成內容照抄（whisper 的已知幻覺）。

    做法：把提示以標點切成 ≥4 字的片段，從回應裡全部挖掉（也挖掉少最後一字的版本：服務常改結尾，
    例「逐字記錄」→「逐字記錄音」），剩下的字不到原本 3 成就算回聲。回應很短或是空的不算。"""
    body = _PUNCT.sub("", text)
    if len(body) < 6:
        return False
    pieces = sorted({p for p in _PUNCT.split(prompt) if len(p) >= min_chunk}, key=len, reverse=True)
    rest = body
    for p in pieces:
        rest = rest.replace(p, "")
        if len(p) > min_chunk:
            rest = rest.replace(p[:-1], "")
    return len(rest) <= threshold * len(body)


def bad_ratio(segs: list[Segment], start: float, end: float) -> float:
    """這一段（start–end）裡幻覺迴圈佔的時間比例；判準跟整場的去重同一支。"""
    from .dedup import collapse_hallucinations, hallucination_coverage

    _, runs = collapse_hallucinations(list(segs))
    return hallucination_coverage(runs, end - start, start)


def _clock(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def find_utterances(samples, sr: int) -> list[tuple[float, float]]:
    """用音量切出有人講話的句子 [(start, end), ...]（秒）。"""
    import numpy as np

    x = np.asarray(samples)
    scale = 32768.0 if x.dtype == np.int16 else 1.0
    n = max(1, int(FRAME * sr))
    frames = len(x) // n
    if frames == 0:
        return []
    rms = np.empty(frames, dtype=np.float32)
    block = 20000  # 分塊算，長會議不必整段轉成 float（一小時 16 kHz float32 約 230 MB）
    for b in range(0, frames, block):
        m = min(block, frames - b)
        blk = x[b * n:(b + m) * n].astype(np.float32) / scale
        rms[b:b + m] = np.sqrt(np.mean(blk.reshape(m, n) ** 2, axis=1))
    audible = rms[rms > 1e-6]
    if not len(audible):
        return []
    # 上限＝中位數 × 0.8：全程都在講、沒有停頓的錄音（或音量一直很平的音檔），底噪 × 2 會高過說話聲，整段被丟掉
    thr = min(float(np.percentile(audible, NOISE_PERCENTILE)) * NOISE_MULT, float(np.median(audible)) * 0.8)
    voiced = rms > thr
    out: list[tuple[float, float]] = []
    start = last = None
    count = 0
    for i in range(frames):
        t = i * FRAME
        if start is None:
            if voiced[i]:
                start, last, count = max(0.0, t - PREROLL), t, 1
            continue
        if voiced[i]:
            last, count = t, count + 1
        if t - last >= END_SILENCE or t - start >= MAX_UTTERANCE:
            if count * FRAME >= MIN_VOICED:
                out.append((round(start, 3), round(t + FRAME, 3)))
            start = None
    if start is not None and count * FRAME >= MIN_VOICED:
        out.append((round(start, 3), round(frames * FRAME, 3)))
    return out


def utterance_bad(text: str) -> bool:
    """這一句的回應看起來是服務亂回的：同幾個字一直重複，或 YouTube 式的固定幻覺句（Amara.org 等）。"""
    from .dedup import SUSPECT_PATTERNS, inner_loop

    low = text.lower()
    return inner_loop(text) or any(p.lower() in low for p in SUSPECT_PATTERNS)


def transcribe(wav: Path, work_dir: Path, base_url: str, model: str, key: str, language: str,
               prompt: str | None, log=print, chunk_seconds: float = CHUNK_SECONDS,
               local_repair=None, split: str | None = None) -> tuple[list[Segment], dict]:
    """回 (段落, 給 run.json 的資訊)。預設一句一句送；split="chunk"（或 MEETING_LOCAL_STT_SPLIT=chunk）走舊的 10 分鐘一段。"""
    if (split or SPLIT) == "chunk":
        return transcribe_chunks(wav, work_dir, base_url, model, key, language, prompt, log=log,
                                 chunk_seconds=chunk_seconds, local_repair=local_repair)
    return transcribe_sentences(wav, work_dir, base_url, model, key, language, prompt, log=log,
                                local_repair=local_repair)


def transcribe_sentences(wav: Path, work_dir: Path, base_url: str, model: str, key: str, language: str,
                         prompt: str | None, log=print, local_repair=None) -> tuple[list[Segment], dict]:
    """一句一句送。某一句亂回（utterance_bad）就換個溫度重送那一句一次；送完後連續 GAP_REPAIR_SECONDS 以上
    都是幻覺的區段，交給 local_repair 用本機補轉（壞的合計不到全場 LOCAL_REPAIR_MAX 才補）。
    原始回應存 work_dir/stt-api/responses.jsonl，出事不必重傳；切出來的音檔送完就刪。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    import numpy as np
    import soundfile as sf

    from .dedup import collapse_hallucinations, merged_spans

    out = work_dir / "stt-api"
    out.mkdir(parents=True, exist_ok=True)
    x, sr = sf.read(str(wav), dtype="int16")
    if getattr(x, "ndim", 1) > 1:
        x = x.mean(axis=1).astype(np.int16)
    duration = len(x) / sr if sr else 0.0
    utts = find_utterances(x, sr)
    if not utts:
        raise ApiError("錄音裡偵測不到有人講話（整段太安靜）。可以改用本機轉，或確認錄音來源")
    voiced = sum(e - s for s, e in utts)
    log(f"切成 {len(utts)} 句（有聲音的 {voiced / 60:.1f} 分鐘，全長 {duration / 60:.1f} 分）→ {host_of(base_url)}，"
        f"同時送 {WORKERS} 句")
    t0 = time.time()
    lock = threading.Lock()
    stats = {"bytes": 0, "requests": 0, "retried": 0, "done": 0}
    step = max(1, len(utts) // 10)

    def one(k: int):
        s, e = utts[k]
        piece = out / f"utt-{k:04d}.wav"
        sf.write(str(piece), np.asarray(x[int(s * sr): int(e * sr)]), sr, subtype="PCM_16")
        size = piece.stat().st_size
        try:
            resp = request_chunk(piece, base_url, model, key, language, prompt)
            n, retried = 1, False
            if utterance_bad(str(resp.get("text", ""))):
                try:
                    again = request_chunk(piece, base_url, model, key, language, None, temperature=RETRY_TEMPERATURE)
                    n, retried = 2, True
                    if not utterance_bad(str(again.get("text", ""))):
                        resp = again
                except ApiError:
                    pass  # 重試本身失敗：維持第一次的結果，後面的幻覺處理會標出來
        finally:
            piece.unlink(missing_ok=True)
        with lock:
            stats["bytes"] += size * n
            stats["requests"] += n
            stats["retried"] += int(retried)
            stats["done"] += 1
            if stats["done"] % step == 0 or stats["done"] == len(utts):
                log(f"線上辨識 {stats['done']}/{len(utts)} 句")
        return k, resp

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(WORKERS) as pool:
        for fut in as_completed([pool.submit(one, k) for k in range(len(utts))]):
            k, resp = fut.result()  # 401／403 等不能重試的錯誤會在這裡丟出來，整場停下
            results[k] = resp
    with (out / "responses.jsonl").open("w", encoding="utf-8") as f:
        for k in range(len(utts)):
            f.write(json.dumps({"i": k, "start": utts[k][0], "end": utts[k][1], "resp": results[k]},
                               ensure_ascii=False) + "\n")
    segments: list[Segment] = []
    for k in range(len(utts)):
        segments.extend(segments_from_response(results[k], utts[k][0], utts[k][1]))

    # 連續一分鐘以上都是幻覺（服務對某一段整片亂回）→ 只用本機補那一段
    _, runs = collapse_hallucinations([Segment(s.start, s.end, s.text) for s in segments])
    gaps = [(s, e) for s, e in merged_spans(runs) if e - s >= GAP_REPAIR_SECONDS]
    repairs: list[dict] = []
    fixed_n = 0
    if gaps and local_repair is not None:
        bad = sum(e - s for s, e in gaps)
        if bad / (duration or 1.0) >= LOCAL_REPAIR_MAX:
            log(f"⚠️ 壞掉的區段佔全場 {bad / (duration or 1.0):.0%}，多半是會議語言選錯或只錄了麥克風，不逐段用本機補")
        else:
            log(f"改用本機補轉 {len(gaps)} 段（共 {bad / 60:.1f} 分鐘），其餘維持線上結果；這幾段不會再上傳")
            try:
                fixed = local_repair(gaps)
            except Exception as exc:  # 本機補不起來不該讓整場失敗：維持線上結果，摘要會標缺段
                log(f"⚠️ 本機補轉失敗（{exc}），這幾段維持線上結果")
                repairs = [{"start": round(s, 1), "end": round(e, 1), "local_error": str(exc)[:200]} for s, e in gaps]
                fixed = []
            for (s, e), segs_local in zip(gaps, fixed):
                keep = [z for z in segments if not (s <= (z.start + z.end) / 2 < e)]
                segments = sorted(keep + list(segs_local), key=lambda z: z.start)
                repairs.append({"start": round(s, 1), "end": round(e, 1), "local_segments": len(segs_local)})
                fixed_n += 1
    info = {"engine": "api", "base_url_host": host_of(base_url), "model": model, "split": "sentence",
            "utterances": len(utts), "requests": stats["requests"], "voiced_seconds": round(voiced, 1),
            "uploaded_bytes": stats["bytes"], "seconds": round(time.time() - t0), "local": False,
            "utterance_retries": stats["retried"], "chunks": len(utts)}
    if repairs:
        info["local_repairs"] = repairs
        info["local_repaired_chunks"] = fixed_n
    return segments, info


def transcribe_chunks(wav: Path, work_dir: Path, base_url: str, model: str, key: str, language: str,
                      prompt: str | None, log=print, chunk_seconds: float = CHUNK_SECONDS,
                      local_repair=None) -> tuple[list[Segment], dict]:
    """舊做法（MEETING_LOCAL_STT_SPLIT=chunk）：切成約 10 分鐘一段。每段的原始回應存 work_dir/stt-api/。

    每段回來就檢查：大半是幻覺迴圈的段落，先不帶提示、換個溫度線上重送一次；還是壞的，
    全部送完後交給 local_repair（[(start, end), ...] → 每段的段落，時間已是整場的絕對秒數）用本機補轉。
    壞段加起來超過全場 LOCAL_REPAIR_MAX 就不補，交給呼叫端的整場失敗流程。"""
    out = work_dir / "stt-api"
    out.mkdir(parents=True, exist_ok=True)
    chunks = plan_chunks_for(wav, chunk_seconds)
    per_chunk: list[list[Segment]] = []
    ratios: list[float] = []
    repairs: list[dict] = []
    sent = 0
    retried = 0
    t0 = time.time()
    for i, (start, end) in enumerate(chunks, 1):
        flac = cut_flac(wav, start, end, out / f"chunk-{i:02d}.flac")
        size = flac.stat().st_size
        if size > UPLOAD_LIMIT:
            raise ApiError(f"第 {i} 段 {size / 1e6:.1f} MB，超過多數服務的 25 MB 上限；把 MEETING_LOCAL_STT_CHUNK_SECONDS 調小再試")
        log(f"上傳第 {i}/{len(chunks)} 段（{start / 60:.1f}–{end / 60:.1f} 分，{size / 1e6:.1f} MB）→ {host_of(base_url)}")
        resp = request_chunk(flac, base_url, model, key, language, prompt)
        (out / f"chunk-{i:02d}.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
        if prompt and is_prompt_echo(str(resp.get("text", "")), prompt):
            log(f"⚠️ 第 {i} 段的結果幾乎都是提示詞的回聲（服務把提示當成要照抄的內容），不帶提示重送一次")
            resp = request_chunk(flac, base_url, model, key, language, None)
            (out / f"chunk-{i:02d}.retry.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
            sent += size
            retried += 1
        sent += size
        segs = segments_from_response(resp, start, end)
        ratio = bad_ratio(segs, start, end)
        if ratio >= CHUNK_BAD:
            log(f"⚠️ 第 {i} 段（{_clock(start)}–{_clock(end)}）有 {ratio:.0%} 是重複的幻覺，線上再試一次（不帶提示）")
            try:
                again = request_chunk(flac, base_url, model, key, language, None, temperature=RETRY_TEMPERATURE)
            except ApiError as exc:  # 重試本身失敗不該拖垮整場：維持第一次的結果，交給本機補轉
                log(f"   線上重試失敗（{exc}），維持第一次的結果")
                again = {}
            else:
                (out / f"chunk-{i:02d}.redo.json").write_text(json.dumps(again, ensure_ascii=False), encoding="utf-8")
                sent += size
            segs2 = segments_from_response(again, start, end)
            ratio2 = bad_ratio(segs2, start, end) if segs2 else 1.0
            repairs.append({"chunk": i, "start": round(start, 1), "end": round(end, 1),
                            "before": round(ratio, 3), "api_retry": round(ratio2, 3)})
            if ratio2 < ratio:
                segs, ratio = segs2, ratio2
            log(f"   重試後幻覺 {ratio2:.0%}" + ("，這段好了" if ratio < CHUNK_BAD else "，還是壞的"))
        flac.unlink(missing_ok=True)  # 音檔切片不留：原檔 audio.wav 還在
        per_chunk.append(segs)
        ratios.append(ratio)

    bad = [k for k, r in enumerate(ratios) if r >= CHUNK_BAD]
    local_fixed = 0
    if bad and local_repair is not None:
        total = (chunks[-1][1] - chunks[0][0]) or 1.0
        bad_sec = sum(chunks[k][1] - chunks[k][0] for k in bad)
        if bad_sec / total >= LOCAL_REPAIR_MAX:
            log(f"⚠️ 壞掉的段落佔全場 {bad_sec / total:.0%}，多半是會議語言選錯或只錄了麥克風，不逐段用本機補")
        else:
            spans = [chunks[k] for k in bad]
            log(f"改用本機補轉 {len(bad)} 段（共 {bad_sec / 60:.1f} 分鐘），其餘維持線上結果；這幾段不會再上傳")
            try:
                fixed = local_repair(spans)
            except Exception as exc:  # 本機補不起來不該讓整場失敗：維持線上結果，摘要會標缺段
                log(f"⚠️ 本機補轉失敗（{exc}），這幾段維持線上結果")
                fixed = None
                for k in bad:
                    _repair_rec(repairs, k + 1)["local_error"] = str(exc)[:200]
            for k, segs_local in zip(bad, fixed or []):
                r = bad_ratio(segs_local, *chunks[k])
                _repair_rec(repairs, k + 1)["local"] = round(r, 3)
                if r < ratios[k]:
                    per_chunk[k], ratios[k] = segs_local, r
                    local_fixed += 1
    segments = [s for segs in per_chunk for s in segs]
    info = {"engine": "api", "base_url_host": host_of(base_url), "model": model, "chunks": len(chunks),
            "uploaded_bytes": sent, "seconds": round(time.time() - t0), "local": False,
            "prompt_echo_retries": retried}
    if repairs:
        info["chunk_repairs"] = repairs
        info["local_repaired_chunks"] = local_fixed
    return segments, info


def _repair_rec(repairs: list[dict], chunk: int) -> dict:
    return next(r for r in repairs if r["chunk"] == chunk)
