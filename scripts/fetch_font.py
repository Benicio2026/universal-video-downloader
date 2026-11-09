#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download Noto Sans CJK SC for bundling into the Android APK.

The font is licensed under the SIL Open Font License 1.1.
It is not committed to the repository; run this script before building.
"""

import sys
import urllib.request
from pathlib import Path

DEST = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "fonts"
    / "NotoSansCJKsc-Regular.otf"
)

URLS = [
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
    "https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
]


def main():
    if DEST.exists() and DEST.stat().st_size > 1_000_000:
        print(f"Font already present: {DEST}")
        return 0

    DEST.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for url in URLS:
        try:
            print(f"Downloading {url}")
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "universal-video-downloader"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if len(data) < 1_000_000:
                last_error = "downloaded file too small"
                continue
            DEST.write_bytes(data)
            print(f"Saved {DEST} ({len(data)} bytes)")
            return 0
        except Exception as exc:
            last_error = exc

    print(f"Failed to download font: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
