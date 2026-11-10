"""App 內更新（只對安裝版）：查 GitHub 最新版 → curl 下載 dmg、比對 SHA-256 → 關掉 App 後換新版並重開。

為什麼要自己做：App 沒有付費的 Apple 公證。用瀏覽器下載的 dmg 會被 macOS 標成「從網路下載」，每次更新都要再過一次
「無法打開 → 仍要打開」；用 curl 下載不會有這個標記，所以從 App 裡更新不會再被擋（同官網的 install.sh）。

網路：只連 api.github.com 與 github.com（Releases），不送任何會議內容。自動檢查每天最多一次，設定 update_check 可關。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config

REPO = "dvdmaru/echoic-local"
DMG = "EchoicLocal-mac-arm64.dmg"
SUMS = "SHA256SUMS.txt"
API = os.environ.get("ECHOIC_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")
CHECK_EVERY = 24 * 3600


def parse_version(s: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def app_bundle() -> Path | None:
    """安裝版的 .app 根目錄；原始碼執行回 None。"""
    if not config.FROZEN:
        return None
    for p in Path(sys.executable).resolve().parents:
        if p.suffix == ".app":
            return p
    return None


def _curl(args: list[str], run=subprocess.run, timeout: int = 900) -> bytes:
    proc = run(["curl", "-fsSL", "--max-time", str(timeout), *args], capture_output=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"連不上 GitHub（curl rc={proc.returncode}）：{proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return proc.stdout


def latest_release(run=subprocess.run) -> dict:
    """{"version": "0.4.1", "dmg": url, "sums": url, "page": url}；Release 少了 dmg 或 SHA 檔就當作沒有可用的新版。"""
    data = json.loads(_curl(["-H", "Accept: application/vnd.github+json", API], run=run, timeout=20))
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets") or []}
    if DMG not in assets or SUMS not in assets:
        raise RuntimeError("最新版的 Release 缺安裝檔或 SHA256SUMS.txt，先不更新")
    return {"version": str(data.get("tag_name") or "").lstrip("v"), "dmg": assets[DMG], "sums": assets[SUMS],
            "page": data.get("html_url") or f"https://github.com/{REPO}/releases/latest"}


def expected_sha(sums_text: str, name: str = DMG) -> str | None:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def staged_path(bundle: Path) -> Path:
    return bundle.parent / ".echoic-local-update.app"


def prepare(release: dict, bundle: Path, log=print, run=subprocess.run) -> Path:
    """下載、比對、把新版複製到舊版旁邊（還沒換掉舊版）。回新版的路徑。"""
    work = Path(tempfile.mkdtemp(prefix="echoic-update-"))
    mnt: str | None = None
    try:
        dmg = work / DMG
        log(f"⬇️ 下載 {release['version']}（約 55 MB）…")
        dmg.write_bytes(_curl([release["dmg"]], run=run))
        want = expected_sha(_curl([release["sums"]], run=run, timeout=30).decode("utf-8", "replace"))
        got = sha256(dmg)
        if not want or want != got:
            raise RuntimeError("下載的安裝檔和官方公布的 SHA-256 不符，已停止更新（舊版沒動）")
        log(f"✅ SHA-256 相符：{got[:12]}…")
        out = run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", str(dmg)],
                  capture_output=True, text=True, stdin=subprocess.DEVNULL)
        vols = [ln.split("\t")[-1].strip() for ln in out.stdout.splitlines() if "/Volumes/" in ln]
        mnt = vols[-1] if vols else None
        src = Path(mnt) / bundle.name if mnt else None
        if not src or not src.is_dir():
            raise RuntimeError(f"安裝檔裡找不到 {bundle.name}，已停止更新")
        new = staged_path(bundle)
        run(["rm", "-rf", str(new)], check=True)
        cp = run(["ditto", str(src), str(new)], capture_output=True, text=True)
        if cp.returncode != 0:
            raise RuntimeError(f"沒辦法寫入 {bundle.parent}（{cp.stderr.strip()[:120]}）：請改用官網的安裝方式")
        run(["xattr", "-dr", "com.apple.quarantine", str(new)], capture_output=True)
        return new
    finally:
        if mnt:
            run(["hdiutil", "detach", "-quiet", mnt], capture_output=True)
        run(["rm", "-rf", str(work)], capture_output=True)


SWAP_SCRIPT = """#!/bin/bash
# Echoic 本機版更新：等舊版結束 → 換成新版 → 重開。由 App 產生，跑完自己刪掉。
OLD="$1"; NEW="$2"; PID="$3"; OPEN="$4"
for _ in $(seq 1 120); do kill -0 "${PID}" 2>/dev/null || break; sleep 0.5; done
if [ -d "${NEW}" ]; then
  rm -rf "${OLD}" && mv "${NEW}" "${OLD}"
fi
if [ "${OPEN}" = "1" ]; then open "${OLD}"; fi
rm -f "$0"
"""


def launch_swap(bundle: Path, new: Path, pid: int | None = None, reopen: bool = True) -> Path:
    """寫一支脫離的換版腳本並啟動；呼叫端接著要結束 App。回腳本路徑（測試用）。"""
    script = Path(tempfile.mkstemp(prefix="echoic-swap-", suffix=".sh")[1])
    script.write_text(SWAP_SCRIPT, encoding="utf-8")
    subprocess.Popen(["/bin/bash", str(script), str(bundle), str(new), str(pid or os.getpid()), "1" if reopen else "0"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return script


def due(last_checked: float, now: float | None = None) -> bool:
    return (now or time.time()) - (last_checked or 0) >= CHECK_EVERY
