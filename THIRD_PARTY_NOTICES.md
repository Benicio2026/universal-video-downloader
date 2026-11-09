# Third-Party Notices

This project uses the following open-source components. Their licenses apply
to the respective components; the project's own code is MIT-licensed.

| Component | License | Source |
|---|---|---|
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| Kivy | MIT | https://github.com/kivy/kivy |
| python-for-android | MIT | https://github.com/kivy/python-for-android |
| Buildozer | MIT | https://github.com/kivy/buildozer |
| Python | PSF License | https://www.python.org/psf/license/ |
| Noto Sans CJK SC | SIL Open Font License 1.1 | https://github.com/notofonts/noto-cjk |
| FFmpeg | LGPL (built without `--enable-gpl`) | https://ffmpeg.org/ |
| LAME | LGPL | https://lame.sourceforge.io/ |

## Fonts

The Android build downloads `NotoSansCJKsc-Regular.otf` from the Noto CJK
project. The font is distributed under the SIL Open Font License, Version 1.1.
The full license text is included in `assets/fonts/OFL.txt` and is packaged
with the APK.

## FFmpeg

Starting with v0.3.0, the APK bundles a static FFmpeg executable built for
Android arm64. The build is produced from the official FFmpeg source with
`scripts/build_ffmpeg.sh`; it is configured with `--disable-network`,
`--disable-autodetect` and without `--enable-gpl`. The resulting binary is
distributed under the LGPL. The corresponding source is available at
<https://ffmpeg.org/download.html>; the build script in this repository
documents the exact configuration.

## LAME

The FFmpeg build statically links libmp3lame from LAME 3.100 for MP3 encoding.
LAME is distributed under the LGPL. Source: <https://lame.sourceforge.io/>.

## yt-dlp

yt-dlp is released into the public domain under the Unlicense. This project
uses it as the download/extraction engine and does not claim authorship of it.
