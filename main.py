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
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

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
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import yt_dlp
from yt_dlp.utils import DownloadCancelled

APP_NAME = "万能视频下载器"
APP_VERSION = "0.8.0"
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
    def __init__(self, app, capture=False):
        self.app = app
        self.capture = capture

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return
        self.app.log(msg)

    def info(self, msg):
        self.app.log(msg)

    def warning(self, msg):
        self.app.log("警告：" + msg)
        if self.capture:
            try:
                self.app._parse_warnings.append(str(msg))
            except Exception:
                pass

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
    log_text = StringProperty("")
    use_service = BooleanProperty(True)
    login_expanded = BooleanProperty(False)
    login_notice = StringProperty("")

    def build(self):
        register_cjk_font()
        Builder.load_file(str(Path(__file__).with_name("app.kv")))
        self.title = APP_NAME
        self.cancel_event = threading.Event()
        self.worker = None
        self.download_dir = None
        self.ffmpeg_path = None
        self.quickjs_path = None
        self.js_runtimes = None
        self._wake_lock = None
        self._service_active = False
        self._service_started_at = 0.0
        self._service_files_dir = Path(self.user_data_dir)
        self._service_job_path = self._service_files_dir / "service_job.json"
        self._service_progress_path = (
            self._service_files_dir / "service_progress.json"
        )
        self._service_cancel_path = (
            self._service_files_dir / "service_cancel.flag"
        )
        self.current_title = None
        self.current_label = ""
        self.entries = []
        self.entry_rows = []
        self.success_count = 0
        self.fail_count = 0
        self.login_prompted = False
        self._parse_warnings = []
        self._parse_requires_login = False
        self._parse_login_reason = ""
        self._last_parse_info = None
        self._last_selected = []
        self._last_quality = ""
        self._fallback_running = False
        self._service_last_error = ""
        self._config = {}
        self._config_loaded = False
        self._load_config()
        self._config_loaded = True
        self.cookies_file = Path(self.user_data_dir) / "cookies.txt"
        self.cookies_path = self.cookies_file if self.cookies_file.exists() else None
        return RootWidget()

    def on_start(self):
        self.download_dir = self.get_download_dir()
        self.download_dir_text = str(self.download_dir)
        self.ffmpeg_path = self._find_ffmpeg()
        self.quickjs_path = self._find_quickjs()
        self.js_runtimes = self._runtime_config()
        self.log(f"{APP_NAME} v{APP_VERSION} 就绪")
        self.log("下载能力由开源项目 yt-dlp 提供。")
        if self.quickjs_path:
            self.log("已加载内置 QuickJS，可处理 YouTube 的 JS challenge。")
            threading.Thread(
                target=self._self_test_quickjs, daemon=True
            ).start()
        if self.ffmpeg_path:
            self.log("FFmpeg 路径：" + self.ffmpeg_path)
            threading.Thread(target=self._self_test_ffmpeg, daemon=True).start()
        else:
            self.log("提示：当前版本未内置 FFmpeg，将优先选择音视频合一的单文件格式。")
        if self.cookies_path:
            self.log("已加载本机 cookies.txt。")
        if platform == "android":
            self.log("前台服务下载：" + ("开启" if self.use_service else "关闭"))
            self.request_android_permissions()
            self._refresh_service_paths()
            self._bind_share_intent()
            self._resume_service_if_running()

    def on_pause(self):
        return True

    def on_resume(self):
        if platform == "android":
            self.refresh_download_dir()

    # ------------------------------------------------------------ 配置

    def _config_path(self):
        return Path(self.user_data_dir) / "config.json"

    def _load_config(self):
        try:
            raw = self._config_path().read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._config = data
        except Exception:
            self._config = {}
        self.use_service = bool(self._config.get("use_service", True))

    def _save_config(self):
        if not self._config_loaded:
            return
        try:
            self._config["download_dir"] = (
                str(self.download_dir) if self.download_dir else ""
            )
            self._config["use_service"] = bool(self.use_service)
            self._config_path().write_text(
                json.dumps(self._config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self.log(f"保存设置失败：{exc}")

    def set_use_service(self, value):
        self.use_service = bool(value)
        self._save_config()

    # ------------------------------------------------------------ 分享接收

    def _bind_share_intent(self):
        try:
            from android import activity

            activity.bind(on_new_intent=self._on_new_intent)
            self._check_share_intent()
        except Exception as exc:
            self.log(f"分享接收不可用：{exc}")

    def _on_new_intent(self, intent):
        Clock.schedule_once(lambda dt: self._handle_share_intent(intent))

    def _check_share_intent(self):
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            self._handle_share_intent(activity.getIntent())
        except Exception:
            pass

    def _handle_share_intent(self, intent):
        try:
            if intent is None:
                return
            action = intent.getAction()
            if action is None or "android.intent.action.SEND" not in str(action):
                return
            text = intent.getStringExtra("android.intent.extra.TEXT")
            if not text:
                return
            match = re.search(r"https?://\S+", text)
            if not match:
                self.log("分享内容里没有可识别的链接。")
                return
            url = match.group(0).rstrip(".,;)]}>\"'")
            self.root.ids.url_input.text = url
            self.log("收到分享链接：" + url)
            if not self.busy:
                Clock.schedule_once(lambda dt: self.parse_url(), 0.4)
        except Exception as exc:
            self.log(f"读取分享内容失败：{exc}")

    # ------------------------------------------------------------ 存储 / 权限

    def get_download_dir(self):
        saved = (getattr(self, "_config", {}) or {}).get("download_dir")
        if saved:
            try:
                candidate = Path(saved).expanduser()
                candidate.mkdir(parents=True, exist_ok=True)
                if candidate.is_dir() and os.access(candidate, os.W_OK):
                    return candidate
            except Exception:
                pass
            try:
                self.log(f"自定义保存目录不可用，改用默认目录：{saved}")
            except Exception:
                pass
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

    # ------------------------------------------------------------ 目录选择

    def _quick_dirs(self):
        if platform == "android":
            base = Path("/storage/emulated/0")
            return [
                ("内部存储", base),
                ("Download", base / "Download"),
                ("Movies", base / "Movies"),
                ("DCIM", base / "DCIM"),
                ("Pictures", base / "Pictures"),
            ]
        home = Path.home()
        return [
            ("主目录", home),
            ("下载", home / "Downloads"),
            ("桌面", home / "Desktop"),
        ]

    def choose_download_dir(self):
        start = self.download_dir or self.get_download_dir()
        if not start.is_dir():
            start = (
                Path("/storage/emulated/0")
                if platform == "android"
                else Path.home()
            )
        current = {"path": start}

        content = BoxLayout(
            orientation="vertical", spacing=dp(8), padding=dp(10)
        )
        path_label = Label(
            text=str(start),
            font_size=dp(11),
            color=(0.75, 0.8, 0.88, 1),
            size_hint_y=None,
            height=dp(38),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="center",
        )
        path_label.bind(
            size=lambda inst, size: setattr(inst, "text_size", size)
        )
        content.add_widget(path_label)

        quick = GridLayout(
            cols=3, size_hint_y=None, height=dp(84), spacing=dp(6)
        )
        content.add_widget(quick)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        dir_list = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(2)
        )
        dir_list.bind(minimum_height=dir_list.setter("height"))
        scroll.add_widget(dir_list)
        content.add_widget(scroll)

        buttons = GridLayout(
            cols=2, size_hint_y=None, height=dp(88), spacing=dp(6)
        )
        up_btn = Button(text="上级目录")
        new_btn = Button(text="新建文件夹")
        choose_btn = Button(text="选择此目录")
        cancel_btn = Button(text="取消")
        for btn in (up_btn, new_btn, cancel_btn):
            btn.background_normal = ""
            btn.background_color = (0.16, 0.22, 0.32, 1)
            btn.color = (0.9, 0.93, 0.98, 1)
            btn.font_size = dp(12)
        choose_btn.background_normal = ""
        choose_btn.background_color = (0.23, 0.51, 0.96, 1)
        choose_btn.color = (1, 1, 1, 1)
        choose_btn.font_size = dp(12)
        buttons.add_widget(up_btn)
        buttons.add_widget(new_btn)
        buttons.add_widget(choose_btn)
        buttons.add_widget(cancel_btn)
        content.add_widget(buttons)

        popup = Popup(
            title="选择保存目录", content=content, size_hint=(0.94, 0.92)
        )

        def refresh(path):
            path = Path(path)
            try:
                path = path.resolve()
            except Exception:
                pass
            if not path.is_dir():
                self.log(f"目录不存在：{path}")
                return
            current["path"] = path
            path_label.text = str(path)
            dir_list.clear_widgets()
            entries = []
            try:
                for child in path.iterdir():
                    try:
                        if child.name.startswith("."):
                            continue
                        if child.is_dir():
                            entries.append(child)
                    except Exception:
                        continue
            except Exception as exc:
                self.log(f"无法读取目录：{exc}")
            entries.sort(key=lambda item: item.name.lower())
            if not entries:
                dir_list.add_widget(
                    Label(
                        text="（没有子目录）",
                        font_size=dp(12),
                        color=(0.55, 0.6, 0.7, 1),
                        size_hint_y=None,
                        height=dp(40),
                    )
                )
            for child in entries:
                btn = Button(
                    text=child.name + "/",
                    font_size=dp(12),
                    halign="left",
                    size_hint_y=None,
                    height=dp(40),
                    background_normal="",
                    background_color=(0.09, 0.13, 0.21, 1),
                    color=(0.85, 0.89, 0.96, 1),
                )
                btn.bind(
                    on_release=lambda _btn, target=child: refresh(target)
                )
                dir_list.add_widget(btn)

        def go_up(_btn):
            parent = current["path"].parent
            if parent != current["path"]:
                refresh(parent)

        def pick(_btn):
            path = current["path"]
            test = path / ".uvd_write_test"
            try:
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            except Exception as exc:
                self.log(f"该目录不可写：{exc}")
                return
            self.download_dir = path
            self.download_dir_text = str(path)
            self._save_config()
            self.log("保存目录已改为：" + self.download_dir_text)
            popup.dismiss()

        def new_folder(_btn):
            box = BoxLayout(
                orientation="vertical", spacing=dp(8), padding=dp(12)
            )
            hint = Label(
                text="在 " + str(current["path"]) + " 下新建文件夹",
                font_size=dp(11),
                size_hint_y=None,
                height=dp(40),
                halign="left",
                valign="middle",
            )
            hint.bind(
                size=lambda inst, size: setattr(inst, "text_size", size)
            )
            name_input = TextInput(
                multiline=False,
                font_size=dp(14),
                size_hint_y=None,
                height=dp(44),
            )
            row = BoxLayout(
                size_hint_y=None, height=dp(44), spacing=dp(8)
            )
            ok = Button(
                text="创建", background_color=(0.23, 0.51, 0.96, 1)
            )
            cancel = Button(
                text="取消", background_color=(0.16, 0.22, 0.32, 1)
            )
            row.add_widget(ok)
            row.add_widget(cancel)
            box.add_widget(hint)
            box.add_widget(name_input)
            box.add_widget(row)
            sub = Popup(
                title="新建文件夹", content=box, size_hint=(0.9, 0.4)
            )

            def create(_btn):
                name = name_input.text.strip()
                if not name or "/" in name or "\\" in name:
                    self.log("文件夹名称无效。")
                    return
                target = current["path"] / name
                try:
                    target.mkdir(parents=False, exist_ok=False)
                except Exception as exc:
                    self.log(f"创建失败：{exc}")
                    return
                sub.dismiss()
                refresh(target)

            ok.bind(on_release=create)
            cancel.bind(on_release=lambda _btn: sub.dismiss())
            sub.open()

        for text, path in self._quick_dirs():
            btn = Button(
                text=text,
                font_size=dp(11),
                background_normal="",
                background_color=(0.16, 0.22, 0.32, 1),
                color=(0.85, 0.89, 0.96, 1),
            )
            btn.bind(on_release=lambda _btn, target=path: refresh(target))
            quick.add_widget(btn)

        up_btn.bind(on_release=go_up)
        new_btn.bind(on_release=new_folder)
        choose_btn.bind(on_release=pick)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        refresh(start)
        popup.open()

    def request_android_permissions(self):
        try:
            from android.permissions import Permission, request_permissions

            perms = [
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
            ]
            notif = getattr(Permission, "POST_NOTIFICATIONS", None)
            if notif is not None:
                perms.append(notif)
            request_permissions(perms)
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

    # ------------------------------------------------------------ 后台服务

    def _get_android_files_dir(self):
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            return Path(activity.getFilesDir().getAbsolutePath())
        except Exception:
            return Path(self.user_data_dir)

    def _refresh_service_paths(self):
        self._service_files_dir = self._get_android_files_dir()
        self._service_job_path = self._service_files_dir / "service_job.json"
        self._service_progress_path = (
            self._service_files_dir / "service_progress.json"
        )
        self._service_cancel_path = (
            self._service_files_dir / "service_cancel.flag"
        )

    def _start_android_service(self, entries, quality):
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ServiceClass = autoclass(
                "org.universalvideo.universalvideodownloader.ServiceDownloader"
            )
            activity = PythonActivity.mActivity
            self._service_files_dir = Path(
                activity.getFilesDir().getAbsolutePath()
            )
            self._service_job_path = (
                self._service_files_dir / "service_job.json"
            )
            self._service_progress_path = (
                self._service_files_dir / "service_progress.json"
            )
            self._service_cancel_path = (
                self._service_files_dir / "service_cancel.flag"
            )
            outdir = self.download_dir or self.get_download_dir()
            job = {
                "entries": [
                    {
                        "url": entry["url"],
                        "title": entry.get("title", ""),
                    }
                    for entry in entries
                ],
                "quality": quality,
                "outdir": str(outdir),
                "ffmpeg": self.ffmpeg_path,
                "qjs": self.quickjs_path,
                "cookies": str(self.cookies_path)
                if self.cookies_path and self.cookies_path.exists()
                else None,
            }
            self._service_job_path.write_text(
                json.dumps(job, ensure_ascii=False), encoding="utf-8"
            )
            for path in (
                self._service_progress_path,
                self._service_cancel_path,
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            ServiceClass.start(activity, "")
            self._service_active = True
            self._service_started_at = time.time()
            self.cancel_event.clear()
            self.current_title = None
            self.current_label = ""
            self.login_prompted = False
            self.success_count = 0
            self.fail_count = 0
            self._service_last_error = ""
            self._set_busy(True)
            self.progress = 0
            self.status = f"后台下载 {len(entries)} 个视频…"
            self.log("已交给前台下载服务，退出 App 后仍会继续。")
            Clock.schedule_interval(self._poll_service, 0.5)
            return True
        except Exception as exc:
            self.log(f"后台服务不可用，改用前台下载：{exc}")
            return False

    def _poll_service(self, dt):
        if not self._service_active:
            return False
        try:
            data = json.loads(
                self._service_progress_path.read_text(encoding="utf-8")
            )
        except Exception:
            if time.time() - self._service_started_at > 20:
                self._service_active = False
                self._set_busy(False)
                self.status = "后台服务没有响应"
                self.log("后台服务启动超时，请重试。")
                return False
            return True
        status = data.get("status")
        if status == "starting":
            self.progress = 0
            self.status = (
                f"正在下载 {data.get('index')}/{data.get('total')}："
                f"{data.get('title', '')}"
            )
        elif status == "progress":
            try:
                self.progress = float(data.get("percent") or 0)
            except (TypeError, ValueError):
                self.progress = 0
            speed = data.get("speed") or ""
            eta = data.get("eta") or ""
            parts = [f"{self.progress:.1f}%"]
            if speed:
                parts.append(speed)
            if eta:
                parts.append("剩余 " + eta)
            self.status = (
                f"{data.get('index')}/{data.get('total')} "
                + "  ".join(parts)
            )
        elif status == "processing":
            self.status = (
                f"{data.get('index')}/{data.get('total')} 正在合并…"
            )
        elif status == "error_item":
            error = str(data.get("error") or "")
            self._service_last_error = error
            self.log(
                f"失败：{data.get('title', '')} - {error}"
            )
            if self._is_login_error(error) and not self.login_prompted:
                self.login_prompted = True
                self._ask_login(error)
        elif status == "done":
            self._service_active = False
            self._set_busy(False)
            self.success_count = data.get("success", 0)
            self.fail_count = data.get("fail", 0)
            last_error = str(
                data.get("last_error") or self._service_last_error or ""
            )
            if last_error:
                self.log("服务最后错误：" + last_error)
            if data.get("cancelled"):
                self.status = "已取消"
                self.log("后台下载已取消。")
            else:
                self.progress = 100
                self.status = (
                    f"完成：成功 {self.success_count} 个，"
                    f"失败 {self.fail_count} 个"
                )
                self.log(self.status)
                if self.fail_count and not self._fallback_running:
                    if (
                        last_error
                        and self._is_login_error(last_error)
                        and not self.login_prompted
                    ):
                        self.login_prompted = True
                        self._ask_login(last_error)
                    else:
                        self._fallback_to_inprocess(
                            data.get("failed") or self._last_selected,
                            self._last_quality,
                            last_error,
                        )
            return False
        elif status == "error":
            self._service_active = False
            self._set_busy(False)
            error = str(data.get("error") or "")
            self.status = "后台下载失败"
            self.log("服务错误：" + error)
            traceback_text = str(data.get("traceback") or "")
            if traceback_text:
                self.log(traceback_text[-3000:])
            self._fallback_to_inprocess(
                self._last_selected, self._last_quality, error
            )
            return False
        return True

    def _fallback_to_inprocess(self, failed_items, quality, reason=""):
        if self._fallback_running:
            return
        entries = []
        for item in failed_items or []:
            if isinstance(item, dict) and item.get("url"):
                entries.append(
                    {
                        "url": item["url"],
                        "title": item.get("title") or "",
                    }
                )
        if not entries:
            entries = [dict(entry) for entry in self._last_selected]
        seen = set()
        unique = []
        for entry in entries:
            url = entry.get("url")
            if url and url not in seen:
                seen.add(url)
                unique.append(entry)
        if not unique:
            return
        self._fallback_running = True
        self.log(
            "后台服务失败，改用应用内下载重试。"
            + (("原因：" + reason) if reason else "")
        )
        self.status = "后台服务失败，正在用应用内方式重试…"
        self.cancel_event.clear()
        self.current_title = None
        self.current_label = ""
        self.success_count = 0
        self.fail_count = 0
        self._set_busy(True)
        self.progress = 0
        self.worker = threading.Thread(
            target=self._download_many_worker,
            args=(unique, quality or "最佳画质（自动）"),
            daemon=True,
        )
        self.worker.start()

    def show_service_log(self):
        path = self._service_files_dir / "service.log"
        progress = self._service_progress_path
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            try:
                text = progress.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
        if not text:
            self.log("没有找到服务日志。")
            self.status = "没有服务日志"
            return
        if len(text) > 20000:
            text = text[-20000:]
        self.log("—" * 18 + " 服务日志（尾部） " + "—" * 18)
        for line in text.splitlines()[-250:]:
            self.log(line)
        self.status = "服务日志已输出到日志框"

    def _resume_service_if_running(self):
        try:
            if not self._service_progress_path.exists():
                return
            data = json.loads(
                self._service_progress_path.read_text(encoding="utf-8")
            )
            if data.get("status") in ("starting", "progress", "processing"):
                self._service_active = True
                self._service_started_at = time.time()
                self._set_busy(True)
                self.status = "后台下载进行中…"
                self.log("检测到后台下载仍在进行。")
                Clock.schedule_interval(self._poll_service, 0.5)
        except Exception:
            pass

    # ------------------------------------------------------------ 工具

    def _find_ffmpeg(self):
        if platform == "android":
            try:
                from jnius import autoclass

                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                native_dir = activity.getApplicationInfo().nativeLibraryDir
                candidate = Path(native_dir) / "libffmpeg.so"
                if candidate.exists():
                    try:
                        os.chmod(candidate, 0o755)
                    except Exception:
                        pass
                    return str(candidate)
            except Exception:
                pass
        return shutil.which("ffmpeg")

    def _find_quickjs(self):
        if platform == "android":
            try:
                from jnius import autoclass

                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                native_dir = activity.getApplicationInfo().nativeLibraryDir
                candidate = Path(native_dir) / "libqjs.so"
                if candidate.exists():
                    try:
                        os.chmod(candidate, 0o755)
                    except Exception:
                        pass
                    return str(candidate)
            except Exception:
                pass
        return shutil.which("qjs")

    def _self_test_ffmpeg(self):
        if not self.ffmpeg_path:
            return
        try:
            executable = os.access(self.ffmpeg_path, os.X_OK)
            self.log(
                "FFmpeg 可执行权限：" + ("有" if executable else "无")
            )
            if not executable:
                try:
                    os.chmod(self.ffmpeg_path, 0o755)
                    self.log("已尝试给 FFmpeg 添加可执行权限。")
                except Exception as exc:
                    self.log(f"FFmpeg chmod 失败：{exc}")
            proc = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = (
                (proc.stdout or "") + "\n" + (proc.stderr or "")
            ).strip()
            first = output.splitlines()[0] if output else ""
            if proc.returncode == 0 and first:
                self.log("FFmpeg 自检通过：" + first[:140])
            else:
                self.ffmpeg_path = None
                self.log(
                    f"FFmpeg 自检失败（rc={proc.returncode}），"
                    "本次改为单文件格式下载：" + output[:300]
                )
        except Exception as exc:
            self.ffmpeg_path = None
            self.log(
                f"FFmpeg 无法执行，本次改为单文件格式下载：{exc}"
            )

    def _self_test_quickjs(self):
        if not self.quickjs_path:
            return
        try:
            proc = subprocess.run(
                [self.quickjs_path, "--help"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = (
                (proc.stdout or "") + "\n" + (proc.stderr or "")
            ).strip()
            if "QuickJS" in output:
                first = next(
                    (
                        line
                        for line in output.splitlines()
                        if "QuickJS" in line
                    ),
                    "QuickJS",
                )
                self.log("QuickJS 自检通过：" + first[:120])
            else:
                self.log("QuickJS 自检失败：" + output[:200])
        except Exception as exc:
            self.log(f"QuickJS 无法执行：{exc}")

    def _runtime_config(self):
        if self.quickjs_path:
            return {"quickjs": {"path": self.quickjs_path}}
        for name in ("deno", "node", "bun"):
            if shutil.which(name):
                return {name: {}}
        return None

    def _set_busy(self, busy):
        self.busy = busy
        if platform == "android":
            try:
                Window.keep_screen_on = bool(busy)
            except Exception:
                pass
            try:
                from jnius import autoclass

                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Context = autoclass("android.content.Context")
                PowerManager = autoclass("android.os.PowerManager")
                context = PythonActivity.mActivity
                if busy:
                    if self._wake_lock is None:
                        pm = context.getSystemService(Context.POWER_SERVICE)
                        self._wake_lock = pm.newWakeLock(
                            PowerManager.PARTIAL_WAKE_LOCK,
                            "UniversalVideoDownloader:download",
                        )
                        self._wake_lock.acquire()
                elif self._wake_lock is not None:
                    try:
                        self._wake_lock.release()
                    except Exception:
                        pass
                    self._wake_lock = None
            except Exception:
                pass

    def set_status(self, text):
        self.status = text

    def log(self, message):
        Clock.schedule_once(lambda dt: self._append_log(message))

    def _append_log(self, message):
        text = self.log_text + ANSI_RE.sub("", str(message)).rstrip() + "\n"
        if len(text) > 60000:
            text = text[-50000:]
        self.log_text = text
        try:
            scroll = self.root.ids.log_scroll
            if scroll.scroll_y <= 0.05:
                Clock.schedule_once(
                    lambda dt: setattr(scroll, "scroll_y", 0), 0.01
                )
        except Exception:
            pass

    def copy_log(self):
        try:
            Clipboard.copy(self.log_text)
            self.status = "日志已复制"
        except Exception as exc:
            self.status = f"复制失败：{exc}"

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
        self._parse_warnings = []
        self._parse_requires_login = False
        self._parse_login_reason = ""
        self._last_parse_info = None
        self.login_prompted = False
        self.login_notice = ""
        self.login_expanded = False
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
            "no_warnings": False,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "logger": YTLogger(self, capture=True),
        }
        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = self._entries_from_info(info, url)
            self._last_parse_info = info
            self._parse_requires_login = self._info_requires_login(info)
            if self._parse_requires_login:
                self._parse_login_reason = (
                    "该视频需要登录才能获取可下载格式。"
                )
            Clock.schedule_once(lambda dt: self._on_parse_done(entries, None))
        except Exception as exc:
            message = str(exc)
            if self._is_login_error(message):
                self._parse_requires_login = True
                self._parse_login_reason = message
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
                self._ask_login(error)
            return
        if not entries:
            self.status = "没有找到可下载的视频"
            self.log("没有找到可下载的视频。")
            return
        self.entries = entries
        self._render_entries()
        self.status = f"解析到 {len(entries)} 个视频，勾选后下载"
        self.log(f"解析到 {len(entries)} 个视频。")
        if self._parse_requires_login:
            self.log(
                "检测到该视频需要登录；点击“下载选中”时会询问是否登录。"
            )

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

    def _info_requires_login(self, info):
        if not info:
            return False
        if info.get("_type") == "playlist" or info.get("entries") is not None:
            return False
        if info.get("_need_login") or info.get("requires_login"):
            return True
        availability = str(info.get("availability") or "").lower()
        if availability in (
            "private",
            "premium_only",
            "subscriber_only",
            "needs_auth",
        ):
            return True
        formats = info.get("formats") or []
        usable = []
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            ext = str(fmt.get("ext") or "").lower()
            if ext in ("mhtml", "none"):
                continue
            if (
                fmt.get("vcodec") == "none"
                and fmt.get("acodec") == "none"
            ):
                continue
            usable.append(fmt)
        if not usable and not info.get("url"):
            return True
        hard_keywords = [
            "login required",
            "log in to",
            "sign in to confirm",
            "private video",
            "members-only",
            "members only",
            "requires authentication",
            "not a bot",
            "confirm you're not a bot",
        ]
        joined = " ".join(self._parse_warnings).lower()
        return any(key in joined for key in hard_keywords)

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
        if self._parse_requires_login and not self.login_prompted:
            self.login_prompted = True
            self._ask_login(
                self._parse_login_reason or "该视频需要登录才能下载。",
                continue_callback=lambda: self._launch_download(
                    selected, quality
                ),
            )
            return
        self._launch_download(selected, quality)

    def _launch_download(self, selected, quality):
        self._last_selected = list(selected)
        self._last_quality = quality
        if quality == "仅音频" and not self.ffmpeg_path:
            self.log("提示：未检测到 FFmpeg，将保存原始音频格式（m4a/webm），不会转码为 MP3。")
        if (
            platform == "android"
            and self.use_service
            and self._start_android_service(selected, quality)
        ):
            return
        self.cancel_event.clear()
        self.current_title = None
        self.current_label = ""
        self.login_prompted = False
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
        if quality == "兼容模式":
            return "best[ext=mp4]/best", []
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
        if self.ffmpeg_path and quality != "兼容模式":
            opts["ffmpeg_location"] = self.ffmpeg_path
        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)
        if self.js_runtimes:
            opts["js_runtimes"] = self.js_runtimes
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
                message = str(exc)
                low = message.lower()
                retry_needed = (
                    quality != "兼容模式"
                    and self.ffmpeg_path
                    and any(
                        key in low
                        for key in ("ffmpeg", "merge", "postprocess", "merging")
                    )
                )
                if retry_needed:
                    Clock.schedule_once(
                        lambda dt, name=title: self.log(
                            f"合并失败，尝试单文件格式重试：{name}"
                        )
                    )
                    try:
                        with yt_dlp.YoutubeDL(
                            self._make_opts("兼容模式")
                        ) as ydl:
                            ydl.download([entry["url"]])
                        self.success_count += 1
                        continue
                    except Exception as retry_exc:
                        message = str(retry_exc)
                        Clock.schedule_once(
                            lambda dt, msg=message: self.log(
                                "兼容模式也失败：" + msg
                            )
                        )
                self.fail_count += 1
                Clock.schedule_once(
                    lambda dt, name=title, msg=message: self.log(
                        f"失败：{name}\n{msg}"
                    )
                )
                if self._is_login_error(message) and not self.login_prompted:
                    self.login_prompted = True
                    Clock.schedule_once(
                        lambda dt, msg=message: self._ask_login(msg)
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
        self._fallback_running = False
        if self.cancel_event.is_set():
            self.status = "已取消"
            self.log("下载已取消。")
        else:
            if self.fail_count == 0:
                self.progress = 100
            self.status = f"完成：成功 {self.success_count} 个，失败 {self.fail_count} 个"
            self.log(self.status)

    def cancel_download(self):
        if self._service_active:
            try:
                self._service_cancel_path.write_text(
                    "1", encoding="utf-8"
                )
            except Exception:
                pass
            self.status = "正在取消…"
            return
        if self.busy:
            self.cancel_event.set()
            self.status = "正在取消…"

    # ------------------------------------------------------------ 登录 / cookies

    # ------------------------------------------------------------ 登录 / cookies

    def toggle_login_section(self):
        self.login_expanded = not self.login_expanded
        if not self.login_expanded:
            self.login_notice = ""

    def expand_login_section(self, reason=""):
        self.login_expanded = True
        if reason:
            self.login_notice = reason

    def _ask_login(self, reason="", continue_callback=None):
        self.expand_login_section(
            reason or "该视频需要登录才能下载。"
        )
        content = BoxLayout(
            orientation="vertical", spacing=dp(10), padding=dp(14)
        )
        message = Label(
            text=(
                "该视频需要登录才能访问。\n\n"
                + (reason + "\n\n" if reason else "")
                + "登录会在站点自己的页面上完成，App 不会接触你的账号密码；"
                "登录后只保存 cookies 到本机，不会上传。\n\n"
                "如果不想登录，需要登录的视频将无法下载。"
            ),
            font_size=dp(12),
            halign="left",
            valign="middle",
        )
        message.bind(
            size=lambda inst, size: setattr(inst, "text_size", size)
        )
        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(6),
        )
        login_button = Button(
            text="同意并登录",
            background_color=(0.23, 0.51, 0.96, 1),
        )
        import_button = Button(
            text="导入 cookies",
            background_color=(0.45, 0.3, 0.55, 1),
        )
        buttons.add_widget(login_button)
        buttons.add_widget(import_button)
        if continue_callback is not None:
            continue_button = Button(
                text="不登录，继续",
                background_color=(0.16, 0.22, 0.32, 1),
            )
            buttons.add_widget(continue_button)
        else:
            continue_button = None
        cancel_button = Button(
            text="取消",
            background_color=(0.16, 0.22, 0.32, 1),
        )
        buttons.add_widget(cancel_button)
        content.add_widget(message)
        content.add_widget(buttons)
        popup = Popup(
            title="需要登录",
            content=content,
            size_hint=(0.94, 0.66),
        )

        def do_login(_instance):
            popup.dismiss()
            self.open_login_webview()

        def do_import(_instance):
            popup.dismiss()
            self.show_cookies_dialog()

        def do_continue(_instance):
            popup.dismiss()
            if continue_callback:
                continue_callback()

        def do_cancel(_instance):
            popup.dismiss()
            self.status = "该视频需要登录，无法下载"
            self.log("用户选择不登录，已停止。")

        login_button.bind(on_release=do_login)
        import_button.bind(on_release=do_import)
        if continue_button is not None:
            continue_button.bind(on_release=do_continue)
        cancel_button.bind(on_release=do_cancel)
        popup.open()

    def open_login_webview(self):
        self.expand_login_section(
            "登录在站点官方页面完成，App 不接触账号密码；"
            "cookies 只保存在本机。"
        )
        if platform != "android":
            self.log("桌面端不支持站内登录，请导入 cookies.txt。")
            self.show_cookies_dialog()
            return
        url = self._normalize_url()
        if not url:
            self.status = "请先粘贴需要登录的视频链接"
            return
        try:
            from jnius import autoclass

            PythonActivity = autoclass(
                "org.kivy.android.PythonActivity"
            )
            Intent = autoclass("android.content.Intent")
            LoginActivity = autoclass(
                "org.universalvideo.universalvideodownloader.LoginActivity"
            )
            activity = PythonActivity.mActivity
            self._refresh_service_paths()
            for name in (
                "webview_login_result.json",
                "webview_cookies.txt",
            ):
                try:
                    (self._service_files_dir / name).unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
            intent = Intent(activity, LoginActivity)
            intent.putExtra("url", url)
            activity.startActivity(intent)
            self._login_poll_started = time.time()
            self.log(
                "已打开登录页；登录完成后点页面右上角的“完成登录”。"
            )
            self.status = "请在登录页完成登录"
            Clock.schedule_interval(self._poll_login_result, 0.5)
        except Exception as exc:
            self.log(f"打开登录页失败：{exc}")
            self.show_cookies_dialog()

    def _poll_login_result(self, dt):
        result_path = (
            self._service_files_dir / "webview_login_result.json"
        )
        if result_path.exists():
            try:
                data = json.loads(
                    result_path.read_text(encoding="utf-8")
                )
            except Exception:
                data = {}
            try:
                result_path.unlink()
            except Exception:
                pass
            if data.get("status") == "cancel":
                self.log("已取消登录。")
                self.status = "已取消登录"
                return False
            cookie_path = (
                self._service_files_dir / "webview_cookies.txt"
            )
            if not cookie_path.exists():
                self.log("登录结果里没有 cookies。")
                self.status = "登录未完成"
                return False
            try:
                text = cookie_path.read_text(encoding="utf-8")
                self.cookies_file.write_text(text, encoding="utf-8")
                self.cookies_path = self.cookies_file
                self.log("登录信息已保存，可以重新解析。")
                self.status = "登录信息已保存"
                self.login_notice = "登录信息已保存，正在重新解析…"
                if not self.busy:
                    Clock.schedule_once(
                        lambda dt: self.parse_url(), 0.6
                    )
            except Exception as exc:
                self.log(f"保存 cookies 失败：{exc}")
            return False
        if time.time() - getattr(self, "_login_poll_started", 0) > 600:
            self.log("等待登录页超时，已停止等待。")
            return False
        return True

    def _login_cancelled(self):
        self.status = "已取消登录"
        self.log("已取消登录。")

    def show_cookies_dialog(self):
        self.expand_login_section(
            "cookies 只保存在本机，不会上传。"
        )
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
