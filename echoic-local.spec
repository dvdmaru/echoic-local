# -*- mode: python ; coding: utf-8 -*-
"""Echoic 本機版的 macOS App 定義。

三個原生執行檔（whisper-server、ffmpeg、ffprobe）由 scripts/build-macos-deps.sh 從官方原始碼建出、
由 scripts/build-macos-app.sh 指定，確保產物可在另一台 Apple Silicon Mac 上使用。
"""
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

APP_NAME = "Echoic 本機版"
VERSION = os.environ.get("MEETING_LOCAL_PACKAGE_VERSION", "0.0.0")


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not Path(value).is_file():
        raise SystemExit(f"缺少封裝輸入 {name}：{value or '未設定'}")
    return value


binaries = [
    (required_env("MEETING_LOCAL_PACKAGE_FFMPEG"), "bin"),
    (required_env("MEETING_LOCAL_PACKAGE_FFPROBE"), "bin"),
    (required_env("MEETING_LOCAL_PACKAGE_WHISPER_SERVER"), "bin"),
]
binaries += collect_dynamic_libs("sherpa_onnx")

a = Analysis(
    ["meeting_local/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=[("meeting_local/models-catalog.json", "meeting_local")],
    hiddenimports=["numpy", "soundfile", "sherpa_onnx", "opencc"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name=APP_NAME,
    console=False,
    exclude_binaries=True,
    target_arch="arm64",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name=APP_NAME,
)
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    bundle_identifier="cc.twtools.echoic-local",
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": f"{APP_NAME}需要麥克風權限，才能在這台 Mac 本機錄製會議。錄音只存在這台電腦。",
    },
)
