#!/usr/bin/env bash
# Build a static FFmpeg executable for Android arm64 and place it in
# libs/arm64-v8a/libffmpeg.so so Buildozer packages it as a native library.
# LAME is built as a static library so FFmpeg can encode MP3.
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
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
CC="$TOOLCHAIN/bin/aarch64-linux-android${API}-clang"
CXX="$TOOLCHAIN/bin/aarch64-linux-android${API}-clang++"
AR="$TOOLCHAIN/bin/llvm-ar"
NM="$TOOLCHAIN/bin/llvm-nm"
RANLIB="$TOOLCHAIN/bin/llvm-ranlib"
STRIP="$TOOLCHAIN/bin/llvm-strip"

for tool in "$CC" "$CXX" "$AR" "$NM" "$RANLIB" "$STRIP"; do
  if [ ! -x "$tool" ]; then
    echo "Missing tool: $tool" >&2
    exit 1
  fi
done

WORK="$ROOT/.ffmpeg-build"
rm -rf "$WORK"
mkdir -p "$WORK"

echo "Downloading LAME source..."
curl -L --retry 10 --retry-all-errors --max-time 300 \
  -o "$WORK/lame.tar.gz" \
  "https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz"
tar -xzf "$WORK/lame.tar.gz" -C "$WORK"
LAMESRC="$(find "$WORK" -maxdepth 1 -type d -name 'lame-*' -print -quit)"
if [ -z "$LAMESRC" ]; then
  echo "LAME source directory not found" >&2
  exit 1
fi

cd "$LAMESRC"
echo "Configuring LAME for Android arm64..."
./configure \
  --host=aarch64-linux-android \
  --build=x86_64-pc-linux-gnu \
  --prefix="$WORK/lame" \
  --disable-shared \
  --enable-static \
  --disable-frontend \
  CC="$CC" \
  AR="$AR" \
  RANLIB="$RANLIB" \
  CFLAGS="-fPIC -O2"
echo "Building LAME..."
make -j"$(nproc)"
make install

echo "Downloading FFmpeg source..."
curl -L --retry 10 --retry-all-errors --max-time 300 \
  -o "$WORK/ffmpeg.tar.gz" \
  "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n7.1"
tar -xzf "$WORK/ffmpeg.tar.gz" -C "$WORK"
SRC="$(find "$WORK" -maxdepth 1 -type d -name 'FFmpeg-*' -print -quit)"
if [ -z "$SRC" ]; then
  echo "FFmpeg source directory not found" >&2
  exit 1
fi

cd "$SRC"
echo "Configuring FFmpeg for Android arm64..."
./configure \
  --target-os=android \
  --arch=aarch64 \
  --cpu=armv8-a \
  --enable-cross-compile \
  --sysroot="$TOOLCHAIN/sysroot" \
  --cc="$CC" \
  --cxx="$CXX" \
  --ar="$AR" \
  --nm="$NM" \
  --ranlib="$RANLIB" \
  --strip="$STRIP" \
  --disable-shared \
  --enable-static \
  --enable-ffmpeg \
  --disable-ffplay \
  --disable-ffprobe \
  --disable-doc \
  --disable-debug \
  --disable-symver \
  --disable-network \
  --disable-autodetect \
  --enable-libmp3lame \
  --enable-small \
  --extra-cflags="-fPIC -O2 -I$WORK/lame/include" \
  --extra-ldflags="-L$WORK/lame/lib -Wl,-z,max-page-size=16384"

echo "Building FFmpeg..."
make -j"$(nproc)"

if readelf -d ffmpeg | grep -Eq 'libav(codec|format|util|filter|device|resample|scale)\.so'; then
  echo "ERROR: ffmpeg still links against shared libav libraries" >&2
  readelf -d ffmpeg | grep NEEDED >&2
  exit 1
fi

echo "ffmpeg binary info:"
file ffmpeg
readelf -d ffmpeg | grep NEEDED || true

mkdir -p "$ROOT/libs/arm64-v8a"
install -m 0755 ffmpeg "$ROOT/libs/arm64-v8a/libffmpeg.so"
ls -lh "$ROOT/libs/arm64-v8a/libffmpeg.so"
echo "FFmpeg build complete"
