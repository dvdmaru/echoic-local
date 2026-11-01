"""說話人分離：sherpa-onnx（pyannote segmentation 3.0 ＋ 3D-Speaker ERes2Net 中文 embedding）。
全程本機、無帳號門檻。輸出只給 SPEAKER_00／01…，命名靠人。"""
from __future__ import annotations

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


def diarize(wav: Path, num_speakers: int = -1, threshold: float = 0.5,
            models_dir: Path = config.MODELS_DIR, progress: bool = True) -> list[dict]:
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
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model)),
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
