"""說話人分離：sherpa-onnx（pyannote segmentation 3.0 ＋ 3D-Speaker ERes2Net 中文 embedding）。
全程本機、無帳號門檻。輸出只給 SPEAKER_00／01…，命名靠人。"""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

from . import config
from .srt import Segment


def _curl(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    subprocess.run(["curl", "-fL", "--retry", "3", "-o", str(tmp), url], check=True, stdin=subprocess.DEVNULL)
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"下載的檔案太小，疑似失敗：{url}")
    tmp.rename(dst)


def ensure_models(models_dir: Path = config.MODELS_DIR) -> tuple[Path, Path]:
    seg_model = models_dir / config.SEG_MODEL_DIRNAME / "model.onnx"
    emb_model = models_dir / config.EMB_MODEL_FILENAME
    if not seg_model.exists():
        print(f"⬇️ 下載說話人分段模型 → {models_dir}", file=sys.stderr)
        tar_path = models_dir / "seg.tar.bz2"
        _curl(config.SEG_MODEL_URL, tar_path)
        with tarfile.open(tar_path, "r:bz2") as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(models_dir, filter="data")
            else:  # pragma: no cover
                tf.extractall(models_dir)
        tar_path.unlink(missing_ok=True)
    if not emb_model.exists():
        print(f"⬇️ 下載說話人 embedding 模型 → {models_dir}", file=sys.stderr)
        _curl(config.EMB_MODEL_URL, emb_model)
    if not seg_model.exists():
        raise FileNotFoundError(f"解壓後找不到 {seg_model}")
    return seg_model, emb_model


def _child(wav: str, num_speakers: int, threshold: float, models_dir: str, num_threads: int, nice: int, q) -> None:
    """子程序本體：降優先權（只降自己）→ 分離 → 結果放回 queue。"""
    try:
        if nice:
            os.nice(nice)
        result = diarize(Path(wav), num_speakers, threshold, Path(models_dir), progress=False,
                         num_threads=num_threads, on_progress=lambda pct: q.put(("progress", pct)))
        q.put(("done", result))
    except BaseException as exc:  # 子程序的錯誤要帶回主程序講，不能默默死掉
        q.put(("error", f"{type(exc).__name__}: {exc}"))


def diarize_isolated(wav: Path, num_speakers: int = -1, threshold: float = 0.5,
                     models_dir: Path = config.MODELS_DIR, num_threads: int = 2, nice: int = 0,
                     log=None) -> list[dict]:
    """在獨立子程序裡分離說話人。

    2026-11-10 實測：sherpa-onnx 的 process() 從頭到尾佔著 Python 的 GIL，同程序的其他執行緒
    60 秒裡只排到 1 次。視窗按「轉逐字稿」時分離就跑在視窗程序裡，整個視窗凍住（151 分鐘的會議約 27 分鐘）。
    搬到子程序後視窗照常動，執行緒數與優先權也只影響這一支。

    ☠️ spawn 的子程序會重新 import 啟動它的主程式：主程式一定要有 `if __name__ == "__main__":` 保護
    （meeting-local 指令、`python -m meeting_local.cli`、app.py 都有；app.py 另外要 freeze_support）。
    2026-11-10 實測時用沒保護的腳本呼叫，子程序又跑了一次整條 transcribe（被工作鎖擋下來才沒事）。
    """
    import multiprocessing as mp
    import queue as _queue

    ensure_models(models_dir)  # 下載在主程序做：子程序的輸出使用者看不到
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_child, args=(str(wav), num_speakers, threshold, str(models_dir), num_threads, nice, q),
                       daemon=True)
    proc.start()
    last = -1
    try:
        while True:
            try:
                kind, value = q.get(timeout=1.0)
            except _queue.Empty:
                if not proc.is_alive():
                    raise RuntimeError(f"說話人分離的子程序意外結束（exit {proc.exitcode}）")
                continue
            if kind == "progress":
                if log and value // 10 != last // 10:
                    log(f"   說話人分離 {value}%")
                last = value
            elif kind == "done":
                return value
            else:
                raise RuntimeError(f"說話人分離失敗：{value}")
    finally:
        if proc.is_alive():
            proc.join(timeout=5)
        if proc.is_alive():  # 主程序被中斷（Ctrl-C、例外）：子程序一起收掉
            proc.terminate()
            proc.join(timeout=5)


def diarize(wav: Path, num_speakers: int = -1, threshold: float = 0.5,
            models_dir: Path = config.MODELS_DIR, progress: bool = True, num_threads: int = 1,
            on_progress=None) -> list[dict]:
    import numpy as np
    import sherpa_onnx
    import soundfile as sf

    seg_model, emb_model = ensure_models(models_dir)
    samples, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"diarize 需要 16 kHz，拿到 {sr}")

    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model)),
            num_threads=num_threads,
        ),
        # 2026-11-10 實測（6 分鐘音檔）：1 執行緒 60.8 秒、2 → 44.4 秒、4 → 49.7 秒，三組結果完全相同
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model), num_threads=num_threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not cfg.validate():
        raise RuntimeError("sherpa-onnx diarization config 無效（模型路徑？）")
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    if sd.sample_rate != sr:
        raise ValueError(f"模型取樣率 {sd.sample_rate} ≠ 音檔 {sr}")

    last = {"pct": -1}

    def _cb(done: int, total: int, _arg=None) -> int:
        if on_progress and total:
            on_progress(int(done * 100 / total))
        if progress and total:
            pct = int(done * 100 / total)
            if pct // 10 != last["pct"] // 10:
                last["pct"] = pct
                print(f"   說話人分離 {pct}%", file=sys.stderr)
        return 0

    result = sd.process(np.ascontiguousarray(samples), callback=_cb).sort_by_start_time()
    return [
        {"start": float(r.start), "end": float(r.end), "speaker": f"SPEAKER_{int(r.speaker):02d}"}
        for r in result
    ]


def minor_speakers(diar: list[dict], min_share: float = config.DIARIZE_MIN_SHARE) -> set[str]:
    """發言占比低於 min_share 的零碎群：自動分群常把咳嗽、背景音、短插話切成獨立 speaker。"""
    tt = talk_time(diar)
    total = sum(tt.values()) or 1.0
    return {spk for spk, sec in tt.items() if sec / total < min_share}


def assign_speakers(segments: list[Segment], diar: list[dict], ignore: set[str] | None = None) -> None:
    """每段逐字稿取重疊最多的 speaker；零碎群（ignore）不參與；沒重疊就沿用上一段（幻覺段不標）。"""
    ignore = ignore or set()
    last: str | None = None
    for s in segments:
        if s.flag == "hallucination":
            continue
        overlap: dict[str, float] = defaultdict(float)
        for d in diar:
            if d["speaker"] in ignore:
                continue
            ov = min(s.end, d["end"]) - max(s.start, d["start"])
            if ov > 0:
                overlap[d["speaker"]] += ov
        if overlap:
            s.speaker = max(overlap.items(), key=lambda kv: kv[1])[0]
            last = s.speaker
        else:
            s.speaker = last


def talk_time(diar: list[dict], ignore: set[str] | None = None) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for d in diar:
        if ignore and d["speaker"] in ignore:
            continue
        total[d["speaker"]] += d["end"] - d["start"]
    return {k: round(v, 1) for k, v in sorted(total.items())}
