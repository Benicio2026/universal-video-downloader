[app]
title = 万能视频下载器
package.name = universalvideodownloader
package.domain = org.universalvideo
source.dir = .
source.include_exts = py,kv,png,jpg,otf,ttf,json,txt
source.exclude_dirs = .venv,venv,__pycache__,bin,.buildozer,.git,.github
source.exclude_patterns = *.pyc,*.pyo,*.apk,*.aab,*.zip
version = 0.1.0
# charset-normalizer 3.3.2 ships a py3-none-any wheel. Newer versions get
# resolved to a cp314 Android wheel that p4a fails to install on Python 3.14.
requirements = python3,kivy,yt-dlp,certifi,charset-normalizer==3.3.2
orientation = portrait
fullscreen = 0
icon.filename = icon.png
android.permissions = INTERNET,ACCESS_NETWORK_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.allow_backup = True
android.accept_sdk_license = True
android.logcat_filters = *:S python:D
