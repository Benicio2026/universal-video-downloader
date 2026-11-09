#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""万能视频下载器 —— Kivy + yt-dlp 的跨平台视频下载器。

下载能力来自开源项目 yt-dlp (Unlicense)。
界面、交互与打包逻辑为本项目原创。
"""

import os
import re
import shutil
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import yt_dlp
from yt_dlp.utils import DownloadCancelled

APP_NAME = "万能视频下载器"
APP_VERSION = "0.2.0"
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
    download_dir_text = StringProperty("")
    list_summary = StringProperty("尚未解析")

    def build(self):
        register_cjk_font()
        Builder.load_file(str(Path(__file__).with_name("app.kv")))
        self.title = APP_NAME
        self.cancel_event = threading.Event()
        self.worker = None
        self.download_dir = None
        self.ffmpeg_path = None
        self.current_title = None
        self.current_label = ""
        self.entries = []
        self.entry_rows = []
        self.success_count = 0
        self.fail_count = 0
        self.cookies_file = Path(self.user_data_dir) / "cookies.txt"
        self.cookies_path = self.cookies_file if self.cookies_file.exists() else None
        return RootWidget()

    def on_start(self):
        self.download_dir = self.get_download_dir()
        self.download_dir_text = str(self.download_dir)
        self.ffmpeg_path = self._find_ffmpeg()
        self.log(f"{APP_NAME} v{APP_VERSION} 就绪")
        self.log("下载能力由开源项目 yt-dlp 提供。")
        if not self.ffmpeg_path:
            self.log("提示：当前版本未内置 FFmpeg，将优先选择音视频合一的单文件格式。")
        if self.cookies_path:
            self.log("已加载本机 cookies.txt。")
        if platform == "android":
            self.request_android_permissions()

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

    # ------------------------------------------------------------ 工具

    def _find_ffmpeg(self):
        if platform == "android":
            try:
                from jnius import autoclass

                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                native_dir = activity.getApplicationInfo().nativeLibraryDir
                candidate = Path(native_dir) / "libffmpeg.so"
                if candidate.exists():
                    return str(candidate)
            except Exception:
                pass
        return shutil.which("ffmpeg")

    def _set_busy(self, busy):
        self.busy = busy
        if platform == "android":
            try:
                Window.keep_screen_on = bool(busy)
            except Exception:
                pass

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

    def _normalize_url(self):
        url = self.root.ids.url_input.text.strip()
        if not url:
            return ""
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
            self.root.ids.url_input.text = url
        return url

    # ------------------------------------------------------------ 解析

    def parse_url(self):
        if self.busy:
            return
        url = self._normalize_url()
        if not url:
            self.status = "请先粘贴视频链接"
            return
        self.cancel_event.clear()
        self.clear_entries()
        self._set_busy(True)
        self.progress = 0
        self.status = "正在解析…"
        self.log("—" * 30)
        self.log("解析：" + url)
        self.worker = threading.Thread(
            target=self._parse_worker, args=(url,), daemon=True
        )
        self.worker.start()

    def _parse_worker(self, url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "logger": YTLogger(self),
        }
        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = self._entries_from_info(info, url)
            Clock.schedule_once(lambda dt: self._on_parse_done(entries, None))
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda dt: self._on_parse_done([], message))

    def _entries_from_info(self, info, original_url):
        if not info:
            return []
        entries = []
        if info.get("_type") == "playlist" or info.get("entries") is not None:
            for item in info.get("entries") or []:
                if not item:
                    continue
                entry_url = item.get("webpage_url")
                raw_url = item.get("url")
                if not entry_url and isinstance(raw_url, str) and raw_url.startswith("http"):
                    entry_url = raw_url
                if not entry_url:
                    vid = item.get("id") or raw_url
                    if vid:
                        if "youtube.com" in original_url or "youtu.be" in original_url:
                            entry_url = f"https://www.youtube.com/watch?v={vid}"
                        elif "bilibili.com" in original_url:
                            entry_url = f"https://www.bilibili.com/video/{vid}"
                        else:
                            entry_url = original_url
                if not entry_url:
                    continue
                entries.append(
                    {
                        "url": entry_url,
                        "title": item.get("title") or item.get("id") or "未命名视频",
                        "duration": self._format_duration(
                            item.get("duration_string") or item.get("duration")
                        ),
                        "uploader": item.get("uploader")
                        or item.get("channel")
                        or "",
                    }
                )
        else:
            entries.append(
                {
                    "url": info.get("webpage_url") or original_url,
                    "title": info.get("title") or "未命名视频",
                    "duration": self._format_duration(
                        info.get("duration_string") or info.get("duration")
                    ),
                    "uploader": info.get("uploader") or "",
                }
            )
        if len(entries) > 200:
            self.log(f"条目过多，只显示前 200 个（共 {len(entries)} 个）。")
            entries = entries[:200]
        return entries

    def _format_duration(self, value):
        if not value:
            return ""
        if isinstance(value, str):
            return value
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return ""
        if seconds >= 3600:
            return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _on_parse_done(self, entries, error):
        self._set_busy(False)
        if error:
            self.status = "解析失败"
            self.log("错误：" + error)
            if self._is_login_error(error):
                self._ask_login()
            return
        if not entries:
            self.status = "没有找到可下载的视频"
            self.log("没有找到可下载的视频。")
            return
        self.entries = entries
        self._render_entries()
        self.status = f"解析到 {len(entries)} 个视频，勾选后下载"
        self.log(f"解析到 {len(entries)} 个视频。")

    def _is_login_error(self, text):
        low = text.lower()
        keywords = [
            "login",
            "log in",
            "sign in",
            "sign-in",
            "cookies",
            "private video",
            "members-only",
            "members only",
            "requires authentication",
            "not a bot",
            "confirm you",
        ]
        return any(key in low for key in keywords)

    # ------------------------------------------------------------ 列表

    def clear_entries(self):
        self.entries = []
        self.entry_rows = []
        self.list_summary = "尚未解析"
        try:
            self.root.ids.list_container.clear_widgets()
        except Exception:
            pass

    def _render_entries(self):
        try:
            container = self.root.ids.list_container
        except Exception:
            return
        container.clear_widgets()
        self.entry_rows = []
        for entry in self.entries:
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(54),
                spacing=dp(4),
            )
            checkbox = CheckBox(active=True, size_hint_x=None, width=dp(44))
            checkbox.bind(active=lambda _inst, _val: self._update_summary())
            text = entry.get("title") or "未命名视频"
            extra = entry.get("duration") or entry.get("uploader") or ""
            if extra:
                text += "  ·  " + extra
            label = Label(
                text=text,
                font_size=dp(12),
                color=(0.82, 0.86, 0.94, 1),
                halign="left",
                valign="middle",
                shorten=True,
                shorten_from="right",
                size_hint_x=1,
            )
            label.bind(
                width=lambda inst, width: setattr(inst, "text_size", (width, None))
            )
            label.text_size = (label.width or dp(260), None)
            row.add_widget(checkbox)
            row.add_widget(label)
            container.add_widget(row)
            self.entry_rows.append((entry, checkbox))
        self._update_summary()

    def _update_summary(self):
        selected = sum(1 for _entry, checkbox in self.entry_rows if checkbox.active)
        self.list_summary = f"共 {len(self.entry_rows)} 个，已选 {selected} 个"

    def select_all(self, active):
        for _entry, checkbox in self.entry_rows:
            checkbox.active = active
        self._update_summary()

    # ------------------------------------------------------------ 下载

    def start_download(self):
        if self.busy:
            return
        if not self.entry_rows:
            self.status = "请先点“解析”获取视频列表"
            return
        selected = [entry for entry, checkbox in self.entry_rows if checkbox.active]
        if not selected:
            self.status = "请勾选要下载的视频"
            return
        quality = self.root.ids.quality_spinner.text
        if quality == "仅音频" and not self.ffmpeg_path:
            self.log("提示：未检测到 FFmpeg，将保存原始音频格式（m4a/webm），不会转码为 MP3。")
        self.cancel_event.clear()
        self.current_title = None
        self.current_label = ""
        self.success_count = 0
        self.fail_count = 0
        self._set_busy(True)
        self.progress = 0
        self.status = f"准备下载 {len(selected)} 个视频…"
        self.log("—" * 30)
        self.log(f"开始下载 {len(selected)} 个视频。")
        self.worker = threading.Thread(
            target=self._download_many_worker,
            args=(selected, quality),
            daemon=True,
        )
        self.worker.start()

    def _format_for(self, quality):
        has_ffmpeg = bool(self.ffmpeg_path)
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

    def _make_opts(self, quality):
        if self.download_dir is None:
            self.download_dir = self.get_download_dir()
        fmt, postprocessors = self._format_for(quality)
        opts = {
            "outtmpl": str(self.download_dir / "%(title).120B [%(id)s].%(ext)s"),
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
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path
        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)
        return opts

    def _download_many_worker(self, entries, quality):
        total = len(entries)
        for index, entry in enumerate(entries, 1):
            if self.cancel_event.is_set():
                break
            title = entry.get("title") or entry.get("url") or "未命名视频"
            Clock.schedule_once(
                lambda dt, i=index, t=total, name=title: self._begin_item(i, t, name)
            )
            try:
                with yt_dlp.YoutubeDL(self._make_opts(quality)) as ydl:
                    ydl.download([entry["url"]])
                self.success_count += 1
            except DownloadCancelled:
                self.cancel_event.set()
                break
            except Exception as exc:
                self.fail_count += 1
                message = str(exc)
                Clock.schedule_once(
                    lambda dt, name=title, msg=message: self.log(
                        f"失败：{name}\n{msg}"
                    )
                )
        Clock.schedule_once(lambda dt: self._on_many_done(total))

    def _begin_item(self, index, total, title):
        self.current_label = f"{index}/{total}"
        self.current_title = None
        self.progress = 0
        self.status = f"正在下载 {index}/{total}：{title}"
        self.log(f"[{index}/{total}] {title}")

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
            Clock.schedule_once(
                lambda dt: self._update_progress(pct, speed, eta, title)
            )
        elif status == "finished":
            Clock.schedule_once(
                lambda dt: setattr(
                    self, "status", f"{self.current_label}  正在处理…"
                )
            )

    def _postprocessor_hook(self, data):
        if data.get("status") == "started":
            name = data.get("postprocessor", "")
            Clock.schedule_once(
                lambda dt: setattr(
                    self, "status", f"{self.current_label}  正在处理：{name}"
                )
            )

    def _update_progress(self, pct, speed, eta, title):
        self.progress = max(0.0, min(100.0, pct))
        parts = [f"{pct:.1f}%"]
        if speed:
            parts.append(speed)
        if eta:
            parts.append("剩余 " + eta)
        prefix = self.current_label or "下载中"
        self.status = prefix + "  " + "  ·  ".join(parts)
        if title and title != self.current_title:
            self.current_title = title
            self.log("标题：" + title)

    def _on_many_done(self, total):
        self._set_busy(False)
        if self.cancel_event.is_set():
            self.status = "已取消"
            self.log("下载已取消。")
        else:
            if self.fail_count == 0:
                self.progress = 100
            self.status = f"完成：成功 {self.success_count} 个，失败 {self.fail_count} 个"
            self.log(self.status)

    def cancel_download(self):
        if self.busy:
            self.cancel_event.set()
            self.status = "正在取消…"

    # ------------------------------------------------------------ 登录 / cookies

    def _ask_login(self):
        content = BoxLayout(
            orientation="vertical", spacing=dp(10), padding=dp(14)
        )
        message = Label(
            text="该视频需要登录才能访问。\n\n"
            "可以导入浏览器导出的 cookies.txt 后重新解析；"
            "如果不想登录，将无法下载。\n\n"
            "cookies 只保存在本机，不会上传。",
            font_size=dp(13),
            halign="left",
            valign="middle",
        )
        message.bind(
            size=lambda inst, size: setattr(inst, "text_size", size)
        )
        buttons = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8)
        )
        import_button = Button(text="导入 cookies.txt", background_color=(0.23, 0.51, 0.96, 1))
        cancel_button = Button(text="取消", background_color=(0.16, 0.22, 0.32, 1))
        buttons.add_widget(import_button)
        buttons.add_widget(cancel_button)
        content.add_widget(message)
        content.add_widget(buttons)
        popup = Popup(
            title="需要登录",
            content=content,
            size_hint=(0.92, 0.55),
        )

        def do_import(_instance):
            popup.dismiss()
            self.show_cookies_dialog()

        def do_cancel(_instance):
            popup.dismiss()
            self.status = "该视频需要登录，无法下载"
            self.log("用户选择不登录，已停止。")

        import_button.bind(on_release=do_import)
        cancel_button.bind(on_release=do_cancel)
        popup.open()

    def show_cookies_dialog(self):
        content = BoxLayout(
            orientation="vertical", spacing=dp(8), padding=dp(12)
        )
        hint = Label(
            text="粘贴浏览器导出的 cookies.txt 内容。\n只保存在本机，不会上传。",
            font_size=dp(12),
            size_hint_y=None,
            height=dp(46),
            halign="left",
            valign="middle",
        )
        hint.bind(size=lambda inst, size: setattr(inst, "text_size", size))
        text_input = TextInput(
            multiline=True,
            font_size=dp(12),
            background_color=(0.05, 0.08, 0.15, 1),
            foreground_color=(0.9, 0.93, 0.98, 1),
        )
        buttons = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8)
        )
        save_button = Button(text="保存", background_color=(0.23, 0.51, 0.96, 1))
        cancel_button = Button(text="取消", background_color=(0.16, 0.22, 0.32, 1))
        buttons.add_widget(save_button)
        buttons.add_widget(cancel_button)
        content.add_widget(hint)
        content.add_widget(text_input)
        content.add_widget(buttons)
        popup = Popup(
            title="导入 cookies.txt",
            content=content,
            size_hint=(0.94, 0.82),
        )

        def do_save(_instance):
            raw = text_input.text.strip()
            if not raw:
                self.log("cookies 内容为空。")
                return
            try:
                self.cookies_file.write_text(raw, encoding="utf-8")
                self.cookies_path = self.cookies_file
                self.log("cookies 已保存，可以重新解析。")
                popup.dismiss()
            except Exception as exc:
                self.log(f"保存 cookies 失败：{exc}")

        save_button.bind(on_release=do_save)
        cancel_button.bind(on_release=lambda _inst: popup.dismiss())
        popup.open()


if __name__ == "__main__":
    UniversalDownloaderApp().run()
