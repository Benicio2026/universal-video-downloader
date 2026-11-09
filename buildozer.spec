[app]
title = 万能视频下载器
package.name = universalvideodownloader
package.domain = org.universalvideo
source.dir = .
source.include_exts = py,kv,png,jpg,otf,ttf,json,txt
source.exclude_dirs = .venv,venv,__pycache__,bin,.buildozer,.git,.github,libs
source.exclude_patterns = *.pyc,*.pyo,*.apk,*.aab,*.zip
version = 0.3.0
# Local Kivy recipe: requests is dropped from python_depends to avoid the
# charset-normalizer cp314 wheel issue in p4a on Python 3.14.
p4a.local_recipes = local_recipes
requirements = python3,kivy,yt-dlp,certifi
orientation = portrait
fullscreen = 0
icon.filename = icon.png
android.permissions = INTERNET,ACCESS_NETWORK_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.add_libs_arm64_v8a = libs/arm64-v8a/libffmpeg.so
android.allow_backup = True
android.accept_sdk_license = True
android.logcat_filters = *:S python:D
