#!/usr/bin/env bash
# 從官方原始碼建 arm64 原生執行檔（whisper-server、ffmpeg、ffprobe）。產物只寫入 build/（已被 gitignore）。
# 版本鎖在 tag，clone 後比對 commit，不符就停（上游 tag 被改或拿錯來源時不會默默用別的碼）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/build/vendor"
RUNTIME_BIN="$ROOT/build/runtime/bin"
CMAKE_BIN="${MEETING_LOCAL_CMAKE:-}"

WHISPER_TAG="v1.9.5"
WHISPER_COMMIT="d1be6fde11ac6e0407606b4e42fe72d34add8037"
FFMPEG_TAG="n9.0.2"
FFMPEG_COMMIT="946fcce07b6dcd0331c8cc609192aeff5e1924f8"
WHISPER_SRC="$VENDOR/whisper.cpp-$WHISPER_TAG"
FFMPEG_SRC="$VENDOR/FFmpeg-$FFMPEG_TAG"

if [ -z "$CMAKE_BIN" ] && [ -x "$ROOT/.venv/bin/python" ]; then
  CMAKE_BIN="$($ROOT/.venv/bin/python -c 'import cmake, pathlib; print(pathlib.Path(cmake.__file__).parent / "data/bin/cmake")' 2>/dev/null || true)"
fi
if [ -z "$CMAKE_BIN" ] || [ ! -x "$CMAKE_BIN" ]; then
  echo "找不到可用的 arm64 CMake。先執行：uv pip install --python .venv/bin/python 'cmake>=3.30'" >&2
  exit 1
fi

mkdir -p "$VENDOR" "$RUNTIME_BIN"

fetch_pinned() {  # <repo url> <tag> <commit> <dir>
  if [ ! -d "$4/.git" ]; then
    git clone --depth 1 --branch "$2" "$1" "$4"
  fi
  local got
  got="$(git -C "$4" rev-parse HEAD)"
  if [ "$got" != "$3" ]; then
    echo "❌ ${4} 的 commit 是 ${got}，預期 ${3}（${2}）。停止。" >&2
    exit 1
  fi
}

fetch_pinned https://github.com/ggml-org/whisper.cpp.git "$WHISPER_TAG" "$WHISPER_COMMIT" "$WHISPER_SRC"
arch -arm64 "$CMAKE_BIN" -S "$WHISPER_SRC" -B "$WHISPER_SRC/build-arm64" \
  -DGGML_METAL=ON \
  -DGGML_METAL_EMBED_LIBRARY=ON \
  -DGGML_NATIVE=OFF \
  -DBUILD_SHARED_LIBS=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_C_FLAGS="-mcpu=apple-m1" \
  -DCMAKE_CXX_FLAGS="-mcpu=apple-m1"
arch -arm64 "$CMAKE_BIN" --build "$WHISPER_SRC/build-arm64" --config Release -j --target whisper-server
cp "$WHISPER_SRC/build-arm64/bin/whisper-server" "$RUNTIME_BIN/whisper-server"

# FFmpeg 用預設（LGPL）設定，不加 --enable-gpl／--enable-nonfree；授權說明見 THIRD_PARTY.md。
fetch_pinned https://github.com/FFmpeg/FFmpeg.git "$FFMPEG_TAG" "$FFMPEG_COMMIT" "$FFMPEG_SRC"
if [ ! -x "$FFMPEG_SRC/ffmpeg" ] || [ ! -x "$FFMPEG_SRC/ffprobe" ]; then
  (
    cd "$FFMPEG_SRC"
    arch -arm64 ./configure --arch=arm64 --cc=clang --disable-debug --disable-doc --disable-shared --enable-static \
      --disable-autodetect --enable-audiotoolbox --enable-avfoundation --enable-zlib
    # --disable-autodetect：不讓 configure 偷接到 Homebrew 的函式庫，否則別台 Mac 開不起來（下面 otool 會驗）
    arch -arm64 /usr/bin/make -j
  )
fi
cp "$FFMPEG_SRC/ffmpeg" "$RUNTIME_BIN/ffmpeg"
cp "$FFMPEG_SRC/ffprobe" "$RUNTIME_BIN/ffprobe"

file "$RUNTIME_BIN/whisper-server" "$RUNTIME_BIN/ffmpeg" "$RUNTIME_BIN/ffprobe"
for b in whisper-server ffmpeg ffprobe; do
  echo "== $b 連結的動態函式庫（只應有系統內建的）"
  otool -L "$RUNTIME_BIN/$b" | tail -n +2
done
