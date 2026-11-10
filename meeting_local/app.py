"""PyInstaller 的 macOS App 入口：不開終端機，直接啟動 Tk 視窗。"""
from __future__ import annotations

# PyInstaller 將這個入口檔當頂層模組執行，不能使用相對匯入；否則另一台
# Mac 啟動時會在建立 Tk 視窗前就拋出「no known parent package」。
import multiprocessing

from meeting_local.ui import main


if __name__ == "__main__":  # pragma: no cover - 由 PyInstaller 呼叫
    # 說話人分離在子程序跑（spawn）：封裝版的子程序也是這支執行檔，freeze_support 讓它認得自己是子程序、
    # 只跑分離不開視窗。少這行，子程序會再開一個視窗。
    multiprocessing.freeze_support()
    raise SystemExit(main())
