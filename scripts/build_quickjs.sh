#!/usr/bin/env bash
# Build QuickJS-ng for Android arm64 and place it in
# libs/arm64-v8a/libqjs.so so Buildozer packages it as a native library.
# yt-dlp runs it as: qjs --script <temp.js>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NDK="${ANDROID_NDK:-/usr/local/lib/android/sdk/ndk/27.3.13750724}"
if [ ! -d "$NDK" ]; then
  NDK="$(ls -d /usr/local/lib/android/sdk/ndk/* 2>/dev/null | sort -V | tail -1)"
fi
if [ ! -d "$NDK" ]; then
  echo "Android NDK not found" >&2
  exit 1
fi

API=24
TAG="v0.12.0"
WORK="$ROOT/.quickjs-build"
rm -rf "$WORK"
mkdir -p "$WORK"

echo "Downloading QuickJS-ng ${TAG}..."
curl -L --retry 10 --retry-all-errors --max-time 300 \
  -o "$WORK/quickjs.tar.gz" \
  "https://codeload.github.com/quickjs-ng/quickjs/tar.gz/refs/tags/${TAG}"
tar -xzf "$WORK/quickjs.tar.gz" -C "$WORK"
SRC="$(find "$WORK" -maxdepth 1 -type d -name 'quickjs-*' -print -quit)"
if [ -z "$SRC" ]; then
  echo "QuickJS source directory not found" >&2
  exit 1
fi

echo "Configuring QuickJS-ng for Android arm64..."
cmake -S "$SRC" -B "$WORK/build" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-${API} \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF

echo "Building qjs..."
cmake --build "$WORK/build" --target qjs_exe -j"$(nproc)"

QJS="$WORK/build/qjs"
if [ ! -x "$QJS" ]; then
  echo "qjs executable not found at $QJS" >&2
  find "$WORK/build" -name 'qjs*' -type f -maxdepth 3 >&2 || true
  exit 1
fi

echo "qjs binary info:"
file "$QJS"
readelf -d "$QJS" | grep NEEDED || true

mkdir -p "$ROOT/libs/arm64-v8a"
install -m 0755 "$QJS" "$ROOT/libs/arm64-v8a/libqjs.so"
ls -lh "$ROOT/libs/arm64-v8a/libqjs.so"
echo "QuickJS build complete"
