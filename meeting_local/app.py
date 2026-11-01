"""PyInstaller 的 macOS App 入口：不開終端機，直接啟動 Tk 視窗。"""
from __future__ import annotations

# PyInstaller 將這個入口檔當頂層模組執行，不能使用相對匯入；否則另一台
# Mac 啟動時會在建立 Tk 視窗前就拋出「no known parent package」。
from meeting_local.ui import main


if __name__ == "__main__":  # pragma: no cover - 由 PyInstaller 呼叫
    raise SystemExit(main())
