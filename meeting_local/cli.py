"""meeting-local：本機會議逐字稿管線 CLI。

  meeting-local ui                     開視窗：開始／停止／波形／一鍵轉逐字稿
  meeting-local doctor                 檢查零件
  meeting-local devices                列音訊裝置
  meeting-local record [--system]      錄音 → ~/Downloads/meetings/<YYYY-MM-DD-HHMM>/audio.wav
  meeting-local transcribe <wav|dir>   正規化＋轉錄（預設關 VAD）＋去重＋繁體＋詞彙表＋說話人分離
  meeting-local diarize <dir>          只重跑說話人分離（調人數／門檻）
  meeting-local entities <dir>         產專名候選表 entities.md（Claude）
  meeting-local summarize <dir>        依 entities.md 產 summary.md（Claude）
  meeting-local all [<wav>]            全部；不給檔就先錄（摘要只在自動摘要開著或加 --summary 時做）
  meeting-local config [--auto-summary on|off]  看或改設定
  meeting-local index                  重建 會議索引.md（Obsidian vault 首頁）
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, config, glossary, joblock, settings
from .audio import (ensure_wav16k, list_audio_devices, measure_levels, normalize_wav, pick_blackhole,
                    pick_microphone, probe, record)
from .dedup import collapse_hallucinations, flag_suspects
from .outputs import update_run_json, write_by_minute, write_speakers_json, write_srt
from .srt import parse_srt
from .tw import fix_punct, run_tw_gate, to_tw
from .whisper import WhisperServer


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- helpers
def _job_dir_for(src: Path | None, name: str | None, out_root: Path) -> Path:
    if name:
        return out_root / name
    if src is not None:
        if src.is_dir():
            return src
        m = re.search(r"(\d{4}-\d{2}-\d{2})[-_T](\d{2})(\d{2})", src.stem)
        if m:
            return out_root / f"{m.group(1)}-{m.group(2)}{m.group(3)}"
        stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime(src.stat().st_mtime))
        return out_root / f"{stamp}-{src.stem[:40]}"
    return out_root / time.strftime("%Y-%m-%d-%H%M")


def _resolve_audio(path: Path) -> Path:
    if path.is_dir():
        cand = path / "audio.wav"
        if not cand.exists():
            raise FileNotFoundError(f"{path} 裡沒有 audio.wav")
        return cand
    if not path.exists():
        raise FileNotFoundError(path)
    return path


_ATTENDEE_SPLIT = re.compile(r"[,，、;；/／\n]+")


def parse_attendees(text: str | None) -> list[str]:
    """「A, B、C」→ ["A","B","C"]；去重、去空白。"""
    if not text:
        return []
    out: list[str] = []
    for name in _ATTENDEE_SPLIT.split(text):
        name = name.strip()
        if name and name not in out:
            out.append(name)
    return out


def _effective_speakers(args: argparse.Namespace) -> int:
    """--speakers 沒給但有與會者名單，就照名單人數分離。"""
    n = getattr(args, "speakers", -1)
    if n is not None and n >= 0:
        return n
    names = parse_attendees(getattr(args, "attendees", None))
    return len(names) if names else -1


def _model_wav(job: Path, wav: Path, args: argparse.Namespace) -> tuple[Path, dict]:
    """給 whisper／分離用的音檔：預設先響度正規化成 audio.norm.wav（原檔不動）。回 (路徑, 原檔音量)。"""
    levels = measure_levels(wav)
    mean = levels.get("mean_db")
    if mean is not None:
        log(f"原檔音量：平均 {mean} dB／峰值 {levels.get('max_db')} dB")
        if mean < config.LOW_LEVEL_DB:
            log(f"⚠️ 錄音偏小聲（低於 {config.LOW_LEVEL_DB:.0f} dB）。這次先正規化再辨識；"
                "輸入音量錄音時已自動拉高，想更好只能讓麥克風靠近講話的人（外接麥克風）。")
    if not config.NORMALIZE or getattr(args, "no_normalize", False):
        return wav, levels
    norm = job / "audio.norm.wav"
    if not norm.exists() or norm.stat().st_mtime < wav.stat().st_mtime:
        t = time.time()
        normalize_wav(wav, norm)
        log(f"響度正規化 → {norm.name}（{time.time()-t:.0f} 秒；原檔不動）")
    return norm, levels


def _memory_hint() -> None:
    try:
        chrome = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        chrome = ""
    free_pct = None
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"free percentage:\s*(\d+)%", out)
        if m:
            free_pct = int(m.group(1))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    warn = []
    if chrome:
        warn.append("Chrome 正在執行")
    if free_pct is not None and free_pct < 30:
        warn.append(f"系統記憶體只剩 {free_pct}%")
    if warn:
        log("⚠️ " + "、".join(warn) + "：whisper large-v3-turbo 需要約 2 GB 記憶體，機器吃緊時會 swap 到很慢。建議先關 Chrome 再跑。")


# ---------------------------------------------------------------- commands
def cmd_doctor(args: argparse.Namespace) -> int:
    ok_all = True

    def row(ok: bool, label: str, detail: str, fix: str = "") -> None:
        nonlocal ok_all
        ok_all &= ok
        mark = "✅" if ok else "❌"
        print(f"{mark} {label}：{detail}")
        if not ok and fix:
            print(f"   → {fix}")

    ff = Path(config.FFMPEG)
    row(ff.exists(), "ffmpeg", str(ff), "安裝版已內附；從原始碼跑請 brew install ffmpeg，或設 MEETING_LOCAL_FFMPEG")
    ws = config.WHISPER_SERVER
    arch = ""
    if ws.exists():
        arch = subprocess.run(["file", str(ws)], capture_output=True, text=True).stdout
        arch = "arm64" if "arm64" in arch else ("x86_64" if "x86_64" in arch else "?")
    row(ws.exists() and arch == "arm64", "whisper-server", f"{ws}（{arch or '不存在'}）",
        "安裝版已內附；從原始碼跑請 brew install whisper-cpp（Apple Silicon 版），或設 MEETING_LOCAL_WHISPER_SERVER")
    row(config.WHISPER_MODEL.exists(), "whisper 模型", str(config.WHISPER_MODEL),
        f"在 App 按「下載語音辨識模型」，或把 ggml-large-v3-turbo.bin（或 q5_0 版）放進 {config.SHARED_MODELS_DIR}")
    row(config.VAD_MODEL.exists(), "VAD 模型（選用）", str(config.VAD_MODEL), "沒有也能跑（--no-vad 行為）；有可減少靜音段幻覺")
    devices = list_audio_devices()
    mic = pick_microphone(devices)
    row(mic is not None, "麥克風", f"{mic[1] if mic else '找不到'}", "系統設定 → 隱私權與安全性 → 麥克風，允許終端機")
    bh = pick_blackhole(devices)
    print(f"{'✅' if bh else '⚠️'} BlackHole 2ch（線上會議錄系統音用）：{bh[1] if bh else '未安裝，--system 會退回只錄麥克風'}")
    cl = Path(config.CLAUDE_BIN)
    auto = "開" if settings.auto_summary() else "關"
    print(f"{'✅' if cl.exists() else '⚠️'} Claude Code（摘要用，選用）：{cl if cl.exists() else '沒裝，只會產出逐字稿'}｜自動摘要：{auto}")
    seg = config.MODELS_DIR / config.SEG_MODEL_DIRNAME / "model.onnx"
    emb = config.MODELS_DIR / config.EMB_MODEL_FILENAME
    print(f"{'✅' if seg.exists() and emb.exists() else '⚠️'} 說話人分離模型：{config.MODELS_DIR}（{'已就緒' if seg.exists() and emb.exists() else '第一次 transcribe 會自動下載約 46 MB'}）")
    tw = config.TW_GATE
    print(f"{'✅' if tw.exists() else '⚠️'} 台灣用語 gate：{tw if tw.exists() else '不存在，會略過'}")
    print(f"ℹ️ 輸出目錄：{config.OUT_ROOT}｜機器：{platform.machine()}｜meeting-local {__version__}")
    return 0 if ok_all else 1


def cmd_config(args: argparse.Namespace) -> int:
    if args.auto_summary:
        settings.save({"auto_summary": args.auto_summary == "on"})
    print(f"自動摘要：{'開' if settings.auto_summary() else '關'}（設定檔 {config.SETTINGS_PATH}）")
    print(settings.SUMMARY_COST_NOTE)
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    for idx, name in list_audio_devices():
        print(f"[{idx}] {name}")
    return 0


def _refresh_index(job: Path) -> None:
    """管線每個階段結束後順手重建 會議索引.md（vault 根＝工作資料夾的上一層）。"""
    from .index import INDEX_NAME, write_index

    try:
        path = write_index(job.parent)
        log(f"📇 索引已更新：{path}")
    except OSError as exc:  # 索引壞了不該讓主流程失敗
        log(f"⚠️ 索引更新失敗（{INDEX_NAME}）：{exc}")


def cmd_index(args: argparse.Namespace) -> int:
    from .index import write_index

    path = write_index(Path(args.out).expanduser())
    log(f"📇 索引已更新：{path}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui import main as ui_main

    return ui_main(Path(args.out))


def cmd_record(args: argparse.Namespace) -> Path:
    job = _job_dir_for(None, args.name, Path(args.out))
    job.mkdir(parents=True, exist_ok=True)
    wav = job / "audio.wav"
    info = record(wav, system_audio=args.system, mic_name=args.mic, source=args.source)
    update_run_json(job / "run.json", job=job.name, record=info, tool_version=__version__)
    log(f"錄音存於 {wav}")
    _refresh_index(job)
    return job


def cmd_transcribe(args: argparse.Namespace) -> Path:
    given = Path(args.path).expanduser()
    src = _resolve_audio(given)
    # 給的是資料夾（record／UI 產的工作資料夾）就在原地做，不要另開副本資料夾。
    job = given if given.is_dir() else _job_dir_for(src, args.name, Path(args.out))
    job.mkdir(parents=True, exist_ok=True)
    joblock.acquire(job, "transcribe")
    wav = job / "audio.wav"
    if src.resolve() != wav.resolve():
        log(f"整理音檔 → {wav}")
        ensure_wav16k(src, wav)
    info = probe(wav)
    log(f"音檔 {info['duration']/60:.1f} 分鐘（{info['codec']} {info['sample_rate']} Hz {info['channels']} ch）")
    _memory_hint()
    model_wav, levels = _model_wav(job, wav, args)

    # 詞彙表：正確寫法進 whisper 提示；沒有檔就放範本
    if glossary.ensure_file(config.GLOSSARY):
        log(f"📝 已放詞彙表範本：{config.GLOSSARY}（填正確寫法與常見錯寫，之後每場都會用）")
    terms = glossary.load(config.GLOSSARY)
    prompt = glossary.whisper_prompt(args.prompt, terms, config.WHISPER_PROMPT_MAX_CHARS)
    if terms:
        log(f"詞彙表 {len(terms)} 條（提示用 {len(prompt)} 字）")
    attendees = parse_attendees(getattr(args, "attendees", None))

    run_json = job / "run.json"
    update_run_json(run_json, job=job.name, source=str(src), audio=info, audio_levels=levels,
                    normalized=(model_wav != wav), attendees=attendees or None, tool_version=__version__)

    # 1. whisper（stderr 導檔，程序保證收掉）
    t0 = time.time()
    use_vad = bool(getattr(args, "vad", False)) and not getattr(args, "no_vad", False)
    server = WhisperServer(log_path=job / "whisper-server.log", vad=use_vad)
    log(f"啟動 whisper-server（port {server.port}，VAD={'on' if server.vad else 'off'}，max-context={server.max_context}），"
        f"log → {server.log_path.name}")
    with server:
        log(f"whisper-server pid {server.pid} 就緒，開始推論（關 VAD 約 12 倍速：43 分鐘音檔要 3～4 分鐘，請等）")
        raw_srt = server.transcribe(model_wav, prompt=prompt)
    assert server.is_gone(), "whisper-server 沒有結束"
    whisper_sec = time.time() - t0
    (job / "transcript.raw.bytes.srt").write_bytes(server.raw_bytes)  # 解碼前原樣，出事不必重跑 whisper
    (job / "transcript.raw.srt").write_text(raw_srt, encoding="utf-8")
    if server.repaired_chars or server.dropped_bytes:
        log(f"⚠️ whisper 輸出有切壞的中文字：接回 {server.repaired_chars} 字，丟掉 {server.dropped_bytes} 處接不回的殘缺字元")
    segments = parse_srt(raw_srt)
    log(f"whisper 完成：{len(segments)} 段，{whisper_sec:.0f} 秒；whisper-server pid {server.pid} 已結束")
    if not segments:
        raise RuntimeError(f"whisper 沒有產出任何段落，看 {job / 'whisper-server.log'}")

    # 2. 幻覺去重 → 3. 繁體
    segments, halluc = collapse_hallucinations(segments, min_run=args.min_run)
    suspects = flag_suspects(segments)
    replaced = 0
    for s in segments:
        s.text = fix_punct(to_tw(s.text))
        s.text, n = glossary.apply(s.text, terms)
        replaced += n
    log(f"幻覺去重：合併 {len(halluc)} 組迴圈（{sum(r['repeats'] for r in halluc)} 段）；疑似幻覺句 {len(suspects)}；"
        f"已轉台灣正體；詞彙表換掉 {replaced} 處錯寫")

    update_run_json(
        run_json,
        models_touched={
            "stt": {"engine": f"whisper.cpp whisper-server ({server.binary})", "model": str(server.model),
                    "vad": server.vad, "max_context": server.max_context, "prompt": prompt,
                    "input": model_wav.name, "local": True},
        },
        whisper_seconds=round(whisper_sec),
        segments=len(segments),
        hallucination_runs=halluc,
        suspect_lines=len(suspects),
        glossary={"path": str(config.GLOSSARY), "terms": len(terms), "replacements": replaced},
    )

    # 4. 說話人分離 → 5. 輸出（共用 _diarize_and_write，diarize 子指令也走同一條）
    _diarize_and_write(job, wav, segments, halluc, args, model_wav=model_wav)
    return job


def _diarize_and_write(job: Path, wav: Path, segments, halluc: list[dict], args: argparse.Namespace,
                       model_wav: Path | None = None) -> None:
    diar: list[dict] = []
    talk: dict[str, float] = {}
    diar_models: dict = {}
    if not getattr(args, "no_diarize", False):
        from .diarize import assign_speakers, diarize, minor_speakers, talk_time

        t1 = time.time()
        n_spk = _effective_speakers(args)
        src_wav = model_wav or wav
        log(f"說話人分離（sherpa-onnx，本機；人數={'自動' if n_spk < 0 else n_spk}，門檻={args.threshold}，音檔={src_wav.name}）…")
        diar = diarize(src_wav, num_speakers=n_spk, threshold=args.threshold)
        minor = minor_speakers(diar) if n_spk < 0 else set()
        assign_speakers(segments, diar, ignore=minor)
        talk = talk_time(diar, ignore=minor)
        diar_models = {"segmentation": config.SEG_MODEL_DIRNAME, "embedding": config.EMB_MODEL_FILENAME,
                       "num_speakers_arg": n_spk, "threshold": args.threshold, "input": src_wav.name,
                       "minor_speakers_absorbed": sorted(minor)}
        log(f"說話人分離完成：{len(talk)} 人（另 {len(minor)} 個零碎群併入前後說話人），{time.time()-t1:.0f} 秒；發言秒數 {talk}")
        write_speakers_json(job / "speakers.json", diar, talk, diar_models)
        if n_spk < 0 and len(talk) > 5:
            log(f"⚠️ 分出 {len(talk)} 個 speaker，真實會議多半是切太碎。知道幾個人就用 --speakers N（或 UI 填與會者），"
                f"或加大 --threshold（例 1.3）後跑 `meeting-local diarize {job}`")

    write_srt(job / "transcript.srt", segments)
    write_by_minute(job / "transcript-by-minute.txt", segments, source=wav.name, halluc_report=halluc)
    rc, gate_out = run_tw_gate(job / "transcript.srt")
    if rc is None:
        log(gate_out)
    else:
        log(f"台灣用語 gate exit {rc}" + ("（乾淨）" if rc == 0 else f"：\n{gate_out}"))
    run_json = job / "run.json"
    prev = update_run_json(run_json)
    touched = dict(prev.get("models_touched") or {})
    touched["diarization"] = {**diar_models, "engine": "sherpa-onnx", "local": True} if diar_models else None
    update_run_json(run_json, models_touched=touched, speakers=talk, tw_gate_exit=rc)
    log(f"✅ 逐字稿完成：{job}")
    for f in ("transcript.srt", "transcript-by-minute.txt", "speakers.json", "whisper-server.log", "run.json"):
        p = job / f
        if p.exists():
            print(f"   {p.name:28s} {p.stat().st_size:>10,d} bytes")
    _refresh_index(job)


_SPEAKER_PREFIX = re.compile(r"^\[(SPEAKER_\d+)\]\s*")


def _load_segments_from_job(job: Path):
    """從既有 transcript.srt 讀回段落（剝掉舊 speaker 前綴、還原幻覺旗標）。"""
    srt_path = job / "transcript.srt"
    if not srt_path.exists():
        raise FileNotFoundError(f"{job} 缺 transcript.srt，先跑 transcribe")
    segments = parse_srt(srt_path.read_text(encoding="utf-8"))
    for s in segments:
        m = _SPEAKER_PREFIX.match(s.text)
        if m:
            s.text = s.text[m.end():]
        if s.text.startswith("[幻覺，已略]"):
            s.flag = "hallucination"
    return segments


def cmd_diarize(args: argparse.Namespace) -> Path:
    """只重跑說話人分離（不重跑 whisper），用來調 --speakers／--threshold。"""
    job = Path(args.path).expanduser()
    if not job.is_dir():
        job = job.parent
    joblock.acquire(job, "diarize")
    wav = job / "audio.wav"
    if not wav.exists():
        raise FileNotFoundError(f"{job} 缺 audio.wav")
    segments = _load_segments_from_job(job)
    prev = update_run_json(job / "run.json")
    halluc = prev.get("hallucination_runs") or []
    if not getattr(args, "attendees", None) and prev.get("attendees"):
        args.attendees = "、".join(prev["attendees"])
    args.no_diarize = False
    norm = job / "audio.norm.wav"
    _diarize_and_write(job, wav, segments, halluc, args, model_wav=norm if norm.exists() else None)
    return job


def cmd_entities(args: argparse.Namespace) -> Path:
    from .summarize import build_entities, plain_text_of

    job = Path(args.path).expanduser()
    if not job.is_dir():
        job = job.parent
    joblock.acquire(job, "entities")
    by_minute_path = job / "transcript-by-minute.txt"
    srt_path = job / "transcript.srt"
    if not by_minute_path.exists() or not srt_path.exists():
        raise FileNotFoundError(f"{job} 缺 transcript-by-minute.txt／transcript.srt，先跑 transcribe")
    segments = parse_srt(srt_path.read_text(encoding="utf-8"))
    log("產專名候選表（claude -p）…")
    gl = glossary.markdown_block(glossary.load(config.GLOSSARY))
    md, rows = build_entities(by_minute_path.read_text(encoding="utf-8"), plain_text_of(segments), model=args.model,
                              glossary_md=gl)
    (job / "entities.md").write_text(md, encoding="utf-8")
    update_run_json(job / "run.json", entities={"count": len(rows), "model": f"claude CLI ({args.model or 'default'})"})
    log(f"✅ entities.md：{len(rows)} 個候選 → {job / 'entities.md'}")
    print("   請打開填「確認正解」欄，再跑 summarize；直接跑也可以，未填的會列成未確認專名。")
    return job


def cmd_summarize(args: argparse.Namespace) -> Path:
    from .summarize import build_summary, safe_title

    job = Path(args.path).expanduser()
    if not job.is_dir():
        job = job.parent
    joblock.acquire(job, "summarize")
    by_minute_path = job / "transcript-by-minute.txt"
    if not by_minute_path.exists():
        raise FileNotFoundError(f"{job} 缺 transcript-by-minute.txt，先跑 transcribe")
    ent_path = job / "entities.md"
    if not ent_path.exists():
        log("沒有 entities.md，先產專名候選表")
        cmd_entities(args)
    entities_md = ent_path.read_text(encoding="utf-8")
    log("產摘要（claude -p）…")
    stamp_m = _STAMP_RE.match(job.name)
    meeting_time = f"{stamp_m.group(1)} {stamp_m.group(2)}:{stamp_m.group(3)}" if stamp_m else None
    prev = update_run_json(job / "run.json")
    attendees = parse_attendees(getattr(args, "attendees", None)) or list(prev.get("attendees") or [])
    gl = glossary.markdown_block(glossary.load(config.GLOSSARY))
    md, title = build_summary(by_minute_path.read_text(encoding="utf-8"), entities_md, source=job.name,
                              model=args.model, meeting_time=meeting_time, attendees=attendees, glossary_md=gl)
    (job / "summary.md").write_text(md, encoding="utf-8")
    update_run_json(job / "run.json", title=title, attendees=attendees or None,
                    summary={"model": f"claude CLI ({args.model or 'default'})", "bytes": len(md.encode("utf-8"))})
    log(f"✅ summary.md → {job / 'summary.md'}｜標題：{title}")

    # 資料夾改名：<時間戳>-<標題>，讓 Finder 一眼看出是哪場。已含標題就不動。
    base = stamp_m.group(0) if stamp_m else job.name
    new_name = f"{base}-{safe_title(title)}"
    if job.name != new_name and not getattr(args, "no_rename", False):
        target = job.parent / new_name
        if target.exists():
            log(f"⚠️ 想改名成 {new_name} 但已存在，資料夾維持 {job.name}")
        else:
            job.rename(target)
            job = target
            log(f"📁 資料夾改名 → {job}")
    _refresh_index(job)
    return job


_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})")


SUMMARY_FAILED = 3  # 逐字稿完成，摘要沒做成（UI 用來分辨「全失敗」）


def want_summary(args: argparse.Namespace) -> bool:
    """--summary／--no-summary 優先；都沒給就照設定檔（預設關：摘要會用到使用者自己的 Claude 額度）。"""
    flag = getattr(args, "summary", None)
    return settings.auto_summary() if flag is None else bool(flag)


def cmd_all(args: argparse.Namespace) -> Path | int:
    if args.path:
        job = cmd_transcribe(args)
    else:
        job = cmd_record(args)
        args.path = str(job)
        job = cmd_transcribe(args)
    args.path = str(job)
    if not want_summary(args):
        log(f"ℹ️ 只做逐字稿（自動摘要沒開）。要這場的摘要：meeting-local summarize \"{job}\"，或在視窗按「產生這場摘要」。")
        return job
    if not config.claude_available():
        log(f"⚠️ 找不到 Claude Code（{config.CLAUDE_BIN}），這次只做逐字稿。裝好並登入後可補做：meeting-local summarize \"{job}\"")
        return SUMMARY_FAILED
    try:
        cmd_entities(args)
        job = cmd_summarize(args)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        log(f"⚠️ 逐字稿已完成，摘要沒做成：{exc}")
        return SUMMARY_FAILED
    return job


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meeting-local", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"meeting-local {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common_out(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--out", default=str(config.OUT_ROOT), help=f"輸出根目錄（預設 {config.OUT_ROOT}）")
        sp.add_argument("--name", help="工作資料夾名稱（預設 YYYY-MM-DD-HHMM）")

    def common_attendees(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--attendees", help="與會者，逗號分隔（例「Amy, David, 小明」）：沒給 --speakers 就照人數分離；摘要依內容推定誰說的")

    def common_diarize(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--speakers", type=int, default=-1, help="說話人數；-1 自動（知道幾個人就給，最準；有 --attendees 時預設照名單人數）")
        sp.add_argument("--threshold", type=float, default=config.DIARIZE_THRESHOLD,
                        help=f"自動分群門檻，越大分出的人越少（預設 {config.DIARIZE_THRESHOLD}；真實會議 0.5 會爆成上百人）")

    def common_transcribe(sp: argparse.ArgumentParser) -> None:
        common_diarize(sp)
        sp.add_argument("--no-diarize", action="store_true", help="跳過說話人分離")
        sp.add_argument("--vad", action="store_true", default=config.WHISPER_VAD,
                        help=f"開 whisper VAD（預設{'開' if config.WHISPER_VAD else '關'}：小聲錄音會被 VAD 當靜音丟掉）")
        sp.add_argument("--no-vad", action="store_true", help="關掉 whisper VAD（蓋過 --vad）")
        sp.add_argument("--no-normalize", action="store_true", help="不做響度正規化，直接用原檔辨識")
        sp.add_argument("--min-run", type=int, default=3, help="連續幾段相同視為幻覺迴圈（預設 3）")
        sp.add_argument("--prompt", default=config.DEFAULT_PROMPT, help="whisper 初始提示（詞彙表的正確寫法會自動接在後面）")

    def common_claude(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--model", default=config.CLAUDE_MODEL, help="claude CLI 模型（預設用 CLI 預設）")
        sp.add_argument("--no-rename", action="store_true", help="摘要後不要把資料夾改成「時間戳-標題」")

    def common_record(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--system", action="store_true", help="同時錄系統音（＝--source both；需 BlackHole 2ch）")
        sp.add_argument("--source", choices=("mic", "system", "both"), default=None,
                        help="錄音來源：mic 只錄麥克風／system 只錄系統音／both 兩者混音（預設 mic，--system 等於 both）")
        sp.add_argument("--mic", help="指定麥克風名稱（子字串）")

    sub.add_parser("doctor", help="檢查零件").set_defaults(func=cmd_doctor)
    sub.add_parser("devices", help="列音訊裝置").set_defaults(func=cmd_devices)

    sp = sub.add_parser("index", help="重建 會議索引.md（Obsidian 用）")
    sp.add_argument("--out", default=str(config.OUT_ROOT), help=f"vault 根目錄（預設 {config.OUT_ROOT}）")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("ui", help="開視窗：開始／停止／波形／一鍵轉逐字稿")
    sp.add_argument("--out", default=str(config.OUT_ROOT), help=f"輸出根目錄（預設 {config.OUT_ROOT}）")
    sp.set_defaults(func=cmd_ui)

    sp = sub.add_parser("record", help="錄音")
    common_out(sp); common_record(sp)
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("transcribe", help="轉錄＋去重＋繁體＋說話人分離")
    sp.add_argument("path", help="wav／任何音訊檔，或已有 audio.wav 的資料夾")
    common_out(sp); common_transcribe(sp); common_attendees(sp)
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("diarize", help="只重跑說話人分離（調 --speakers／--threshold 用，不重跑 whisper）")
    sp.add_argument("path", help="工作資料夾")
    common_diarize(sp); common_attendees(sp)
    sp.set_defaults(func=cmd_diarize)

    sp = sub.add_parser("entities", help="產專名候選表（Claude）")
    sp.add_argument("path", help="工作資料夾")
    common_claude(sp)
    sp.set_defaults(func=cmd_entities)

    sp = sub.add_parser("summarize", help="產摘要（Claude）")
    sp.add_argument("path", help="工作資料夾")
    common_claude(sp); common_attendees(sp)
    sp.set_defaults(func=cmd_summarize)

    sp = sub.add_parser("all", help="錄音（可略）→ 轉錄 →（自動摘要開著才做）專名表 → 摘要")
    sp.add_argument("path", nargs="?", help="已有音檔就給路徑；不給就先錄音")
    common_out(sp); common_record(sp); common_transcribe(sp); common_claude(sp); common_attendees(sp)
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--summary", dest="summary", action="store_true", default=None,
                   help="這次要做摘要（蓋過設定；會用到你 Claude 方案的額度）")
    g.add_argument("--no-summary", dest="summary", action="store_false", help="這次只做逐字稿（蓋過設定）")
    sp.set_defaults(func=cmd_all)

    sp = sub.add_parser("config", help="看或改設定（目前只有自動摘要開關）")
    sp.add_argument("--auto-summary", choices=("on", "off"), help="轉完逐字稿後自動用 Claude 產生摘要")
    sp.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.func(args)
    except KeyboardInterrupt:
        print("\n中斷。", file=sys.stderr)
        return 130
    except (RuntimeError, FileNotFoundError, TimeoutError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    finally:
        joblock.release_all()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
