"""語音辨識模型：找現成的、下載缺的。

和「看懂 KanDong」共用同一個資料夾與同一份清單（models-catalog.json）：
- 兩個工具都會掃共用資料夾（Mac `~/.cache/twtools/models`，Windows `%USERPROFILE%\\.cache\\twtools\\models`）。
- 檔名＋SHA256 相同就是同一顆。Whisper large-v3-turbo 未量化版與 q5_0 版都能用，看到哪顆用哪顆，
  所以裝過看懂的人不必再下載一次。
- 下載先寫 `<檔名>.part`，比對官方 SHA256 才改名。`.part` 60 秒內還在變大，代表另一個程式正在下載，
  這邊就不重開一份。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("models-catalog.json")
WHISPER_FAMILY = "whisper-large-v3-turbo"
# 會議逐字稿偏好未量化版（現有參數都是用它實測的）；只有 q5_0 時照樣能用。
PREFERRED_ORDER = ("ggml-large-v3-turbo.bin", "ggml-large-v3-turbo-q5_0.bin")
ACTIVE_PART_SECONDS = 60


@dataclass(frozen=True)
class ModelEntry:
    file: str
    family: str
    url: str
    sha256: str
    size: int


def _bundle_catalog_path() -> Path:
    # PyInstaller 版把清單放在解開後的 meeting_local/ 底下
    base = Path(getattr(sys, "_MEIPASS", "")) / "meeting_local" / CATALOG_PATH.name
    return base if base.exists() else CATALOG_PATH


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or _bundle_catalog_path()).read_text(encoding="utf-8"))


def entries(path: Path | None = None) -> list[ModelEntry]:
    return [ModelEntry(**{k: m[k] for k in ("file", "family", "url", "sha256", "size")})
            for m in load_catalog(path)["models"]]


def entry(file: str) -> ModelEntry:
    for e in entries():
        if e.file == file:
            return e
    raise KeyError(file)


def shared_dir(home: Path | None = None) -> Path:
    """共用模型資料夾。TWTOOLS_MODELS 可覆蓋（測試或想放外接碟時用）。"""
    override = os.environ.get("TWTOOLS_MODELS")
    if override:
        return Path(override).expanduser()
    home = home or Path.home()
    return home / ".cache" / "twtools" / "models"


def find_whisper(search_dirs: list[Path]) -> Path | None:
    """依偏好順序找現成的 Whisper large-v3-turbo。大小要和清單一致才算（擋掉下載到一半的檔）。

    偏好檔名優先於資料夾順序：哪個資料夾有未量化版就先用，都沒有才用 q5_0。
    """
    sizes = {e.file: e.size for e in entries() if e.family == WHISPER_FAMILY}
    for name in PREFERRED_ORDER:
        for d in search_dirs:
            p = d / name
            try:
                if p.is_file() and p.stat().st_size == sizes[name]:
                    return p
            except OSError:
                continue
    return None


def sha256_of(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def part_in_use(partial: Path, now: float | None = None) -> bool:
    """`.part` 最近 ACTIVE_PART_SECONDS 秒內有寫入＝另一個程式正在下載。"""
    try:
        mtime = partial.stat().st_mtime
    except FileNotFoundError:
        return False
    return (now or time.time()) - mtime < ACTIVE_PART_SECONDS


def download(url: str, target: Path, sha256: str | None, size: int | None,
             label: str, progress=None, min_bytes: int = 0) -> Path:
    """curl 續傳下載到 `<target>.part`，驗大小與 SHA256 後才改名。不用 Python HTTPS，避開本機 CA bundle 問題。"""
    if target.is_file() and (size is None or target.stat().st_size == size):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    if part_in_use(partial):
        raise RuntimeError(f"另一個程式正在下載{label}（{partial}），等它下載完再試一次。")
    need = (size or min_bytes) - (partial.stat().st_size if partial.exists() else 0)
    free = shutil.disk_usage(target.parent).free
    if need > 0 and free < need * 1.05:
        raise RuntimeError(f"磁碟空間不夠下載{label}：還需要 {need / 1e9:.2f} GB，只剩 {free / 1e9:.2f} GB。")
    if progress:
        progress(f"⬇️ 下載{label}…（存到 {target.parent}）")
    proc = subprocess.run(
        ["curl", "-fL", "--retry", "3", "--continue-at", "-", "-o", str(partial), url],
        text=True, capture_output=True, stdin=subprocess.DEVNULL,
    )
    if proc.returncode:
        raise RuntimeError(f"{label}下載失敗：{proc.stderr.strip()[-500:]}")
    got = partial.stat().st_size if partial.exists() else 0
    if (size is not None and got != size) or got < min_bytes:
        raise RuntimeError(f"{label}下載不完整（{got:,} bytes），請重新嘗試")
    if sha256:
        if progress:
            progress(f"🔎 比對{label}的 SHA256…")
        actual = sha256_of(partial)
        if actual != sha256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"{label}的 SHA256 不符（{actual[:12]}…），已刪除，請重新下載")
    partial.replace(target)
    return target
