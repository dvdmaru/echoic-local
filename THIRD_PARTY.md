# 第三方元件與授權

Echoic 本機版自己的程式（`meeting_local/`、`scripts/`、`tests/`）是 MIT 授權，見 `LICENSE`。
Mac 安裝包裡另外附了下列第三方元件，各自依其授權散布。模型都不內附，第一次使用時從官方網址下載。

| 元件 | 用途 | 版本 | 授權 | 原始碼／來源 |
|---|---|---|---|---|
| whisper.cpp（whisper-server） | 語音辨識引擎（內附，自官方原始碼建置） | v1.9.5（commit `d1be6fd`） | MIT | https://github.com/ggml-org/whisper.cpp |
| FFmpeg（ffmpeg、ffprobe） | 錄音、轉檔、響度正規化（內附，自官方原始碼建置） | n9.0.2（commit `946fcce`），未加 `--enable-gpl`／`--enable-nonfree`，靜態連結 | LGPL-2.1-or-later | https://github.com/FFmpeg/FFmpeg ，建置參數見 `scripts/build-macos-deps.sh` |
| sherpa-onnx（含 onnxruntime） | 說話人分離 | 1.13.8 | Apache-2.0（onnxruntime：MIT） | https://github.com/k2-fsa/sherpa-onnx |
| python-soundfile（含 libsndfile） | 讀寫音檔 | 0.14.0 | BSD-3-Clause（libsndfile：LGPL-2.1-or-later） | https://github.com/bastibe/python-soundfile 、https://github.com/libsndfile/libsndfile |
| NumPy | 數值運算 | 2.x | BSD-3-Clause 等 | https://github.com/numpy/numpy |
| opencc-python-reimplemented | 簡繁轉換（台灣正體） | 0.1.7 | Apache-2.0 | https://github.com/yichen0831/opencc-python |
| Python、Tcl/Tk | 執行環境與視窗 | 3.13 | PSF License；Tcl/Tk License | https://www.python.org/ |
| PyInstaller（bootloader） | 打包成 .app | 6.x | GPL-2.0 附 bootloader 例外（允許散布打包產物） | https://github.com/pyinstaller/pyinstaller |
| Whisper large-v3-turbo 模型 | 語音辨識（不內附，下載） | ggml 未量化版或 q5_0 | MIT | https://huggingface.co/ggerganov/whisper.cpp |
| Silero VAD 模型 | 靜音偵測（不內附，下載；預設不啟用） | v6.2.0 ggml | MIT | https://huggingface.co/ggml-org/whisper-vad |
| pyannote segmentation 3.0（sherpa-onnx 轉檔） | 說話人分段（不內附，下載） | — | MIT | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models |
| 3D-Speaker ERes2Net 中文 embedding | 說話人辨識（不內附，下載） | base sv zh-cn 16k | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models |

## LGPL 元件

FFmpeg 與 libsndfile 依 LGPL 散布。對應的原始碼可從上表的上游取得（版本與 commit 已列出，FFmpeg 的建置參數在 `scripts/build-macos-deps.sh`）。
若需要我們提供與安裝包內執行檔完全對應的原始碼，或重新連結所需的目的檔，請在 GitHub 開 issue，我們會提供。

## Claude Code

摘要功能呼叫使用者自己安裝並登入的 Claude Code（Anthropic），本工具不內附、不轉散布它，使用時適用 Anthropic 的條款。
