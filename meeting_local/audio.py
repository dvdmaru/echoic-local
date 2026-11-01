"""ffmpeg／avfoundation：列裝置、錄音、轉成 16 kHz mono s16le wav。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from . import config


def list_audio_devices() -> list[tuple[int, str]]:
    """回傳 [(index, name)]，索引由 ffmpeg 當下輸出解析，不寫死。"""
    proc = subprocess.run(
        [config.FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    text = proc.stderr + proc.stdout
    devices: list[tuple[int, str]] = []
    in_audio = False
    for line in text.splitlines():
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if "AVFoundation video devices" in line:
            in_audio = False
            continue
        if not in_audio:
            continue
        m = re.search(r"\[(\d+)\]\s+(.+?)\s*$", line)
        if m:
            devices.append((int(m.group(1)), m.group(2)))
    return devices


def pick_device(devices: list[tuple[int, str]], *needles: str) -> tuple[int, str] | None:
    for needle in needles:
        for idx, name in devices:
            if needle.lower() in name.lower():
                return idx, name
    return None


def pick_microphone(devices: list[tuple[int, str]], prefer: str | None = None) -> tuple[int, str] | None:
    if prefer:
        return pick_device(devices, prefer)
    hit = pick_device(devices, "microphone", "麥克風", "mic")
    if hit:
        return hit
    for idx, name in devices:
        if not any(bad in name.lower() for bad in ("blackhole", "teams", "zoom", "projector", "virtual")):
            return idx, name
    return None


def pick_blackhole(devices: list[tuple[int, str]]) -> tuple[int, str] | None:
    return pick_device(devices, "blackhole")


def probe(path: Path) -> dict:
    proc = subprocess.run(
        [config.FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失敗：{proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
    }


def is_whisper_ready(path: Path) -> bool:
    info = probe(path)
    return info["codec"] == "pcm_s16le" and info["sample_rate"] == 16000 and info["channels"] == 1


def ensure_wav16k(src: Path, dst: Path) -> Path:
    """任何 ffmpeg 讀得懂的檔 → dst（s16le / 16 kHz / mono）。已合格就直接複製。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return dst
    if src.suffix.lower() == ".wav" and is_whisper_ready(src):
        dst.write_bytes(src.read_bytes())
        return dst
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    return dst


def normalize_wav(src: Path, dst: Path) -> Path:
    """響度正規化（EBU R128 單趟）→ dst（s16le / 16 kHz / mono）。原檔不動。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-af", config.LOUDNORM_FILTER, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    return dst


_VOL_MEAN = re.compile(r"mean_volume:\s*([-\d.]+) dB")
_VOL_MAX = re.compile(r"max_volume:\s*([-\d.]+) dB")


def measure_levels(path: Path) -> dict:
    """整檔平均與峰值音量（dBFS），用 ffmpeg volumedetect；量不到就回 None 值。"""
    proc = subprocess.run(
        [config.FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    m1 = _VOL_MEAN.search(proc.stderr)
    m2 = _VOL_MAX.search(proc.stderr)
    return {"mean_db": float(m1.group(1)) if m1 else None, "max_db": float(m2.group(1)) if m2 else None}


def input_volume() -> int | None:
    """macOS 系統輸入音量 0–100；非 macOS 或讀不到回 None。"""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["osascript", "-e", "input volume of (get volume settings)"],
                             capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
        return int(out) if out.isdigit() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def set_input_volume(level: int) -> bool:
    """把 macOS 系統輸入音量設成 level（0–100）。成功回 True。"""
    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.run(["osascript", "-e", f"set volume input volume {int(level)}"],
                              capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_input_volume(target: int | None = None) -> dict:
    """低於 target 就拉到 target；回 {"before", "after", "changed"}。target 0／讀不到就只回現值。"""
    target = config.AUTO_INPUT_VOLUME if target is None else target
    before = input_volume()
    if not target or before is None or before >= target:
        return {"before": before, "after": before, "changed": False}
    ok = set_input_volume(target)
    after = input_volume() if ok else before
    return {"before": before, "after": after, "changed": ok and after != before}


SOURCES = ("mic", "system", "both")


def build_record_cmd(out_wav: Path, system_audio: bool = False, mic_name: str | None = None,
                     pipe_pcm: bool = False, quiet: bool = False, source: str | None = None) -> tuple[list[str], dict]:
    """組 ffmpeg 錄音指令。pipe_pcm=True 時額外把同一路 s16le/16k/mono 吐到 stdout（UI 畫波形用）。

    source：mic（只錄麥克風）／system（只錄系統音）／both；沒給就看 system_audio（True＝both）。
    回傳 (cmd, info)，info 含 mode／mic／blackhole／warning。
    """
    if source is None:
        source = "both" if system_audio else "mic"
    if source not in SOURCES:
        raise ValueError(f"source 必須是 {SOURCES}")
    devices = list_audio_devices()
    if not devices:
        raise RuntimeError("ffmpeg 列不到任何 avfoundation 音訊裝置（系統設定 → 隱私權 → 麥克風，允許終端機）")
    mic = pick_microphone(devices, mic_name)
    blackhole = pick_blackhole(devices) if source in ("system", "both") else None
    warning = None
    if source == "mic":
        if mic is None:
            raise RuntimeError(f"找不到麥克風裝置。可用裝置：{devices}")
        mode = "mic"
    elif source == "system":
        if blackhole is None:
            raise RuntimeError("只錄系統音需要 BlackHole 2ch，但找不到。裝 BlackHole 並在音訊 MIDI 設定建多輸出設備，見 README。")
        mode = "system"
    else:
        if blackhole is None and mic is None:
            raise RuntimeError(f"麥克風與 BlackHole 都找不到。可用裝置：{devices}")
        if blackhole is None:
            warning = "你要求錄系統音，但找不到 BlackHole 2ch，退回只錄麥克風。線上會議要錄對方聲音需先裝 BlackHole 並設 Multi-Output Device，見 README。"
            mode = "mic"
        elif mic is None:
            warning = "找不到麥克風，只錄系統音。"
            mode = "system"
        else:
            mode = "mic+system"

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG, "-hide_banner", "-loglevel", "warning", "-y"]
    if not quiet:
        cmd.append("-stats")
    # ⚠️ avfoundation 不加 wallclock 時間戳＋async 重取樣會靜默掉音訊：2026-09-14 實測 25 秒只存 21–22 秒（-13～15%），
    # 單麥克風也一樣；加了之後 25.6 秒存 25.1 秒（差的 0.5 秒是開裝置延遲）。
    inputs = {"mic": [mic], "system": [blackhole], "mic+system": [blackhole, mic]}[mode]
    for dev in inputs:
        assert dev is not None
        cmd += ["-use_wallclock_as_timestamps", "1", "-f", "avfoundation", "-i", f":{dev[0]}"]
    if mode == "mic+system":
        graph = ("[0:a]aresample=async=1[x];[1:a]aresample=async=1[y];"
                 "[x][y]amix=inputs=2:duration=longest:dropout_transition=0")
    else:
        graph = "[0:a]aresample=async=1"
    # 限幅：峰值壓在 -1 dBFS，兩路相加或大聲說話都不削波（只動超過門檻的那幾毫秒）。
    graph += "," + config.LIMITER_FILTER
    # 濾鏡輸出標籤只能被 map 一次；要同時寫檔＋吐管線就先 asplit 成兩路。
    graph += ",asplit=2[a][b]" if pipe_pcm else "[a]"
    cmd += ["-filter_complex", graph]
    cmd += ["-map", "[a]", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav)]
    if pipe_pcm:
        cmd += ["-map", "[b]", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"]
    vol = ensure_input_volume() if mode != "system" else {"before": None, "after": None, "changed": False}
    info = {"mode": mode, "mic": mic if mode != "system" else None,
            "blackhole": blackhole if mode != "mic" else None, "warning": warning,
            "input_volume": vol["after"], "input_volume_before": vol["before"],
            "input_volume_changed": vol["changed"]}
    return cmd, info


def input_volume_note(info: dict) -> str | None:
    """開錄時給人看的一句：自動拉了就說從幾到幾；沒拉成又太低就警告；否則只報現值。"""
    vol = info.get("input_volume")
    if vol is None:
        return None
    if info.get("input_volume_changed"):
        return f"輸入音量 {info.get('input_volume_before')} → {vol}/100（自動拉高；Teams／Zoom 開過會會把它調低）"
    if vol < config.AUTO_INPUT_VOLUME:
        return f"⚠️ 系統輸入音量只有 {vol}/100，自動拉高沒成功：系統設定 › 聲音 › 輸入，手動拉到 {config.AUTO_INPUT_VOLUME}。"
    return f"輸入音量 {vol}/100"


def describe_devices(dev: dict) -> str:
    parts = []
    if dev.get("mic"):
        parts.append(f"麥克風＝[{dev['mic'][0]}] {dev['mic'][1]}")
    if dev.get("blackhole"):
        parts.append(f"系統音＝[{dev['blackhole'][0]}] {dev['blackhole'][1]}")
    return "；".join(parts)


def record(out_wav: Path, system_audio: bool = False, mic_name: str | None = None,
           source: str | None = None) -> dict:
    """前景錄音；按 q 或 Ctrl-C 結束。回傳實際用到的裝置資訊。"""
    cmd, dev = build_record_cmd(out_wav, system_audio=system_audio, mic_name=mic_name, source=source)
    mode, mic, blackhole = dev["mode"], dev["mic"], dev["blackhole"]
    if dev["warning"]:
        print(f"⚠️ {dev['warning']}", file=sys.stderr)

    note = input_volume_note(dev)
    if note:
        print(f"   {note}")
    print(f"🎙️ 錄音中（{mode}）：{describe_devices(dev)}")
    print(f"   輸出：{out_wav}")
    print("   結束：按 q 再 Enter，或 Ctrl-C")
    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        # Ctrl-C 同時送到 ffmpeg（同一個 process group），它會自己收尾寫檔頭。
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
    if not out_wav.exists() or out_wav.stat().st_size < 1000:
        raise RuntimeError("錄音檔沒有產出或幾乎是空的；請檢查麥克風權限與裝置")
    info = probe(out_wav)
    levels = measure_levels(out_wav)
    print(f"✅ 錄音完成：{info['duration']:.1f} 秒，{info['codec']} {info['sample_rate']} Hz {info['channels']} ch；"
          f"平均 {levels['mean_db']} dB／峰值 {levels['max_db']} dB")
    if levels["mean_db"] is not None and levels["mean_db"] < config.LOW_LEVEL_DB:
        print(f"⚠️ 錄音偏小聲（平均 {levels['mean_db']} dB，低於 {config.LOW_LEVEL_DB:.0f}）。這次轉錄會先正規化再辨識；"
              "輸入音量已是上限附近，想更好只能讓麥克風靠近講話的人（外接麥克風）。", file=sys.stderr)
    return {"mode": mode, "mic": mic, "blackhole": blackhole, "input_volume": dev.get("input_volume"),
            **info, **levels}
