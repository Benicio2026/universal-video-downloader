#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""万能视频下载器 —— Kivy + yt-dlp 的跨平台视频下载器。

下载能力来自开源项目 yt-dlp (Unlicense)。
界面、交互与打包逻辑为本项目原创。
"""

import json
import os
import re
import shutil
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

import yt_dlp
from yt_dlp.utils import DownloadCancelled

APP_NAME = "万能视频下载器"
APP_VERSION = "0.1.0"
QUALITIES = [
    "最佳画质（自动）",
    "1080p 及以下",
    "720p 及以下",
    "仅音频",
]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def register_cjk_font():
    """注册中文字体。Android 优先使用随 APK 打包的 Noto Sans CJK。"""
    base = Path(__file__).resolve().parent
    candidates = [base / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf"]
    if platform == "android":
        candidates += [
            Path("/system/fonts/NotoSansCJK-Regular.ttc"),
            Path("/system/fonts/NotoSansCJKsc-Regular.otf"),
            Path("/system/fonts/NotoSansSC-Regular.otf"),
        ]
    elif platform == "win":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates += [fonts / "msyh.ttc", fonts / "simhei.ttf", fonts / "simsun.ttc"]
    for path in candidates:
        if path.exists():
            try:
                LabelBase.register(
                    name="Roboto",
                    fn_regular=str(path),
                    fn_bold=str(path),
                    fn_italic=str(path),
                    fn_bolditalic=str(path),
                )
                LabelBase.register(name="CJK", fn_regular=str(path), fn_bold=str(path))
                return str(path)
            except Exception:
                continue
    return None


class YTLogger:
    def __init__(self, app):
        self.app = app

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return
        self.app.log(msg)

    def info(self, msg):
        self.app.log(msg)

    def warning(self, msg):
        self.app.log("警告：" + msg)

    def error(self, msg):
        self.app.log("错误：" + msg)


class RootWidget(BoxLayout):
    pass


class UniversalDownloaderApp(App):
    status = StringProperty("就绪")
    progress = NumericProperty(0)
    busy = BooleanProperty(False)
    proxy = StringProperty("")
    download_dir_text = StringProperty("")

    def build(self):
        register_cjk_font()
        Builder.load_file(str(Path(__file__).with_name("app.kv")))
        self.title = APP_NAME
        self.cancel_event = threading.Event()
        self.worker = None
        self.current_title = None
        self.download_dir = None
        self.config_path = Path(self.user_data_dir) / "config.json"
        return RootWidget()

    def on_start(self):
        self.load_config()
        self.download_dir = self.get_download_dir()
        self.download_dir_text = str(self.download_dir)
        self.log(f"{APP_NAME} v{APP_VERSION} 就绪")
        self.log("下载能力由开源项目 yt-dlp 提供。")
        if not shutil.which("ffmpeg"):
            self.log(
                "提示：当前版本未内置 FFmpeg，将优先选择音视频合一的单文件格式；"
                "高清合并下载会在后续版本加入。"
            )
        if platform == "android":
            self.request_android_permissions()

    def on_stop(self):
        self.proxy = self._proxy_text()
        self.save_config()

    def on_pause(self):
        return True

    def on_resume(self):
        if platform == "android":
            self.refresh_download_dir()

    # ------------------------------------------------------------ 存储 / 权限

    def get_download_dir(self):
        if platform == "android":
            try:
                from android.storage import primary_external_storage_path

                base = (
                    Path(primary_external_storage_path())
                    / "Download"
                    / "UniversalVideoDownloader"
                )
                base.mkdir(parents=True, exist_ok=True)
                return base
            except Exception:
                pass
            base = Path(self.user_data_dir) / "Downloads"
        else:
            base = Path.home() / "Downloads" / "UniversalVideoDownloader"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def refresh_download_dir(self):
        self.download_dir = self.get_download_dir()
        self.download_dir_text = str(self.download_dir)
        self.log("保存目录：" + self.download_dir_text)

    def request_android_permissions(self):
        try:
            from android.permissions import Permission, request_permissions

            request_permissions(
                [
                    Permission.READ_EXTERNAL_STORAGE,
                    Permission.WRITE_EXTERNAL_STORAGE,
                ]
            )
        except Exception as exc:
            self.log(f"权限请求失败：{exc}")

    def open_storage_settings(self):
        if platform != "android":
            self.log("桌面端不需要额外存储权限。")
            return
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            activity = PythonActivity.mActivity
            package = activity.getPackageName()
            try:
                intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                intent.setData(Uri.parse("package:" + package))
                activity.startActivity(intent)
            except Exception:
                intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                activity.startActivity(intent)
            self.log("已打开权限设置；授予“所有文件访问”后返回并点“刷新目录”。")
        except Exception as exc:
            self.log(f"打开权限设置失败：{exc}")

    # ------------------------------------------------------------ 配置

    def load_config(self):
        try:
            if self.config_path.exists():
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.proxy = data.get("proxy", "")
        except Exception:
            self.proxy = ""

    def save_config(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps({"proxy": self.proxy}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _proxy_text(self):
        try:
            return self.root.ids.proxy_input.text.strip()
        except Exception:
            return ""

    # ------------------------------------------------------------ UI 辅助

    def set_status(self, text):
        self.status = text

    def log(self, message):
        Clock.schedule_once(lambda dt: self._append_log(message))

    def _append_log(self, message):
        try:
            widget = self.root.ids.log_input
        except Exception:
            return
        text = widget.text + ANSI_RE.sub("", str(message)).rstrip() + "\n"
        if len(text) > 60000:
            text = text[-50000:]
        widget.text = text

    def paste_url(self):
        try:
            text = Clipboard.paste()
        except Exception:
            text = ""
        if text:
            self.root.ids.url_input.text = text.strip()

    def clear_url(self):
        self.root.ids.url_input.text = ""

    # ------------------------------------------------------------ 下载

    def start_download(self):
        if self.busy:
            return
        url = self.root.ids.url_input.text.strip()
        if not url:
            self.set_status("请先粘贴视频链接")
            return
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
            self.root.ids.url_input.text = url

        proxy = self._proxy_text()
        self.proxy = proxy
        self.save_config()

        quality = self.root.ids.quality_spinner.text
        if quality == "仅音频" and not shutil.which("ffmpeg"):
            self.log("提示：未检测到 FFmpeg，将保存原始音频格式（m4a/webm），不会转码为 MP3。")
        self.cancel_event.clear()
        self.current_title = None
        self.busy = True
        self.progress = 0
        self.set_status("正在解析视频…")
        self.log("—" * 30)
        self.log("开始：" + url)

        self.worker = threading.Thread(
            target=self._download_worker,
            args=(url, quality, proxy),
            daemon=True,
        )
        self.worker.start()

    def _format_for(self, quality):
        has_ffmpeg = bool(shutil.which("ffmpeg"))
        if quality == "仅音频":
            if has_ffmpeg:
                return "bestaudio/best", [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "0",
                    }
                ]
            return "bestaudio/best", []
        if has_ffmpeg:
            if quality == "1080p 及以下":
                return "bv*[height<=1080]+ba/b[height<=1080]", []
            if quality == "720p 及以下":
                return "bv*[height<=720]+ba/b[height<=720]", []
            return "bv*+ba/b", []
        if quality == "1080p 及以下":
            return "best[height<=1080]/best", []
        if quality == "720p 及以下":
            return "best[height<=720]/best", []
        return "best", []

    def _download_worker(self, url, quality, proxy):
        try:
            if self.download_dir is None:
                self.download_dir = self.get_download_dir()
            outdir = self.download_dir
            fmt, postprocessors = self._format_for(quality)
            opts = {
                "outtmpl": str(outdir / "%(title).120B [%(id)s].%(ext)s"),
                "format": fmt,
                "noplaylist": True,
                "noprogress": True,
                "quiet": True,
                "no_warnings": False,
                "logger": YTLogger(self),
                "progress_hooks": [self._progress_hook],
                "postprocessor_hooks": [self._postprocessor_hook],
                "windowsfilenames": True,
                "consoletitle": False,
                "merge_output_format": "mp4",
            }
            if postprocessors:
                opts["postprocessors"] = postprocessors
            if proxy:
                opts["proxy"] = proxy
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                opts["ffmpeg_location"] = ffmpeg

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            Clock.schedule_once(lambda dt: self._on_done(True, outdir))
        except DownloadCancelled:
            Clock.schedule_once(lambda dt: self._on_done(False, None, cancelled=True))
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda dt: self._on_done(False, None, error=message))

    def _progress_hook(self, data):
        if self.cancel_event.is_set():
            raise DownloadCancelled("cancelled")
        status = data.get("status")
        if status == "downloading":
            raw = ANSI_RE.sub("", data.get("_percent_str", "0%"))
            try:
                pct = float(raw.replace("%", "").strip())
            except ValueError:
                pct = 0.0
            speed = ANSI_RE.sub("", data.get("_speed_str", "")).strip()
            eta = ANSI_RE.sub("", data.get("_eta_str", "")).strip()
            title = (data.get("info_dict") or {}).get("title")
            Clock.schedule_once(lambda dt: self._update_progress(pct, speed, eta, title))
        elif status == "finished":
            Clock.schedule_once(lambda dt: self.set_status("下载完成，正在处理…"))

    def _postprocessor_hook(self, data):
        if data.get("status") == "started":
            name = data.get("postprocessor", "")
            Clock.schedule_once(lambda dt: self.set_status(f"正在处理：{name}"))

    def _update_progress(self, pct, speed, eta, title):
        self.progress = max(0.0, min(100.0, pct))
        parts = [f"{pct:.1f}%"]
        if speed:
            parts.append(speed)
        if eta:
            parts.append("剩余 " + eta)
        self.status = "下载中  " + "  ·  ".join(parts)
        if title and title != self.current_title:
            self.current_title = title
            self.log("标题：" + title)

    def _on_done(self, ok, outdir, cancelled=False, error=None):
        self.busy = False
        if cancelled:
            self.status = "已取消"
            self.log("下载已取消。")
        elif ok:
            self.progress = 100
            self.status = "下载完成"
            self.log("完成，文件在：" + str(outdir))
        else:
            self.status = "下载失败"
            self.log("错误：" + (error or "未知错误"))

    def cancel_download(self):
        if self.busy:
            self.cancel_event.set()
            self.status = "正在取消…"


if __name__ == "__main__":
    UniversalDownloaderApp().run()
