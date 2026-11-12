#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android 前台下载服务：由 p4a 启动，在独立进程中执行下载。

App 写入 service_job.json，本服务读取后下载，持续写入
service_progress.json；App 关闭后服务仍可继续。
"""

import json
import os
import re
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled
from jnius import autoclass

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ANDROID_SYSTEM_LIBS = (
    "/system/lib64:/vendor/lib64:/system/lib:/vendor/lib"
)


def ffmpeg_env():
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ANDROID_SYSTEM_LIBS
    env.pop("LD_PRELOAD", None)
    return env


def enable_ffmpeg_hls():
    try:
        from yt_dlp.downloader.external import FFmpegFD

        FFmpegFD.available = classmethod(
            lambda cls, path=None: True
        )
    except Exception:
        pass


@contextmanager
def ffmpeg_child_env():
    old_ld = os.environ.get("LD_LIBRARY_PATH")
    old_preload = os.environ.get("LD_PRELOAD")
    os.environ["LD_LIBRARY_PATH"] = ANDROID_SYSTEM_LIBS
    os.environ.pop("LD_PRELOAD", None)
    try:
        yield
    finally:
        if old_ld is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = old_ld
        if old_preload is not None:
            os.environ["LD_PRELOAD"] = old_preload


class ServiceLogger:
    """把 yt-dlp 的警告/错误写进 service.log，便于在 App 里查看。"""

    def __init__(self, log_fn):
        self.log_fn = log_fn

    def debug(self, msg):
        pass

    def info(self, msg):
        self.log_fn(str(msg))

    def warning(self, msg):
        self.log_fn("警告：" + str(msg))

    def error(self, msg):
        self.log_fn("错误：" + str(msg))


def format_for(quality, has_ffmpeg):
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


def main():
    PythonService = autoclass("org.kivy.android.PythonService")
    service = PythonService.mService
    files_dir = Path(service.getFilesDir().getAbsolutePath())
    job_path = files_dir / "service_job.json"
    progress_path = files_dir / "service_progress.json"
    cancel_path = files_dir / "service_cancel.flag"
    log_path = files_dir / "service.log"

    wake_lock = None
    try:
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)
        wake_lock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "UniversalVideoDownloader:service",
        )
        wake_lock.acquire()
    except Exception:
        pass

    def write_progress(data):
        try:
            tmp = progress_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(progress_path)
        except Exception:
            pass

    def log(message):
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(
                    f"[{time.strftime('%H:%M:%S')}] {message}\n"
                )
        except Exception:
            pass

    try:
        if log_path.exists() and log_path.stat().st_size > 300_000:
            try:
                log_path.unlink()
            except Exception:
                pass
        job = json.loads(job_path.read_text(encoding="utf-8"))
        entries = job.get("entries") or []
        quality = job.get("quality") or "最佳画质（自动）"
        outdir = Path(job.get("outdir") or (files_dir / "Downloads"))
        outdir.mkdir(parents=True, exist_ok=True)
        ffmpeg = job.get("ffmpeg")
        qjs = job.get("qjs")
        cookies = job.get("cookies")
        total = len(entries)
        success = 0
        fail = 0
        cancelled = False
        last_error = ""
        failed = []

        log(
            "服务启动 | python=%s | yt-dlp=%s | entries=%s | quality=%s"
            % (
                sys.version.split()[0],
                yt_dlp.version.__version__,
                total,
                quality,
            )
        )
        log("保存目录：%s" % outdir)
        log("FFmpeg：%s | QuickJS：%s" % (ffmpeg, qjs))
        if ffmpeg:
            log(
                "FFmpeg 检查：exists=%s executable=%s"
                % (os.path.exists(ffmpeg), os.access(ffmpeg, os.X_OK))
            )
            try:
                probe = subprocess.run(
                    [ffmpeg, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    env=ffmpeg_env(),
                )
                probe_out = (
                    (probe.stdout or "")
                    + "\n"
                    + (probe.stderr or "")
                ).strip()
                log(
                    "FFmpeg 自检 rc=%s：%s"
                    % (probe.returncode, probe_out[:500])
                )
                if probe.returncode != 0:
                    ffmpeg = None
                    log("FFmpeg 不可用，改用单文件格式")
            except Exception as exc:
                ffmpeg = None
                log(
                    "FFmpeg 自检异常：%s；改用单文件格式" % exc
                )

        def is_cancelled():
            return cancel_path.exists()

        def make_opts(index, headers=None):
            fmt, postprocessors = format_for(quality, bool(ffmpeg))
            last_write = [0.0]

            def progress_hook(data):
                if is_cancelled():
                    raise DownloadCancelled("cancelled")
                status = data.get("status")
                if status == "downloading":
                    now = time.time()
                    if now - last_write[0] < 0.5:
                        return
                    last_write[0] = now
                    raw = ANSI_RE.sub(
                        "", data.get("_percent_str", "0%")
                    )
                    try:
                        percent = float(
                            raw.replace("%", "").strip()
                        )
                    except ValueError:
                        percent = 0.0
                    downloaded = data.get("downloaded_bytes") or 0
                    total_bytes = (
                        data.get("total_bytes")
                        or data.get("total_bytes_estimate")
                        or 0
                    )
                    fragment_index = (
                        data.get("fragment_index") or 0
                    )
                    fragment_count = (
                        data.get("fragment_count") or 0
                    )
                    if total_bytes:
                        try:
                            percent = (
                                downloaded * 100.0 / total_bytes
                            )
                        except Exception:
                            pass
                    elif fragment_count:
                        try:
                            percent = (
                                fragment_index
                                * 100.0
                                / fragment_count
                            )
                        except Exception:
                            pass
                    write_progress(
                        {
                            "status": "progress",
                            "index": index,
                            "total": total,
                            "title": (data.get("info_dict") or {}).get(
                                "title"
                            )
                            or "",
                            "percent": percent,
                            "downloaded_bytes": downloaded,
                            "total_bytes": total_bytes,
                            "fragment_index": fragment_index,
                            "fragment_count": fragment_count,
                            "speed": ANSI_RE.sub(
                                "", data.get("_speed_str", "")
                            ).strip(),
                            "eta": ANSI_RE.sub(
                                "", data.get("_eta_str", "")
                            ).strip(),
                            "success": success,
                            "fail": fail,
                        }
                    )
                elif status == "finished":
                    write_progress(
                        {
                            "status": "processing",
                            "index": index,
                            "total": total,
                            "success": success,
                            "fail": fail,
                        }
                    )

            opts = {
                "outtmpl": str(
                    outdir / "%(title).120B [%(id)s].%(ext)s"
                ),
                "format": fmt,
                "noplaylist": True,
                "noprogress": True,
                "quiet": True,
                "no_warnings": False,
                "logger": ServiceLogger(log),
                "progress_hooks": [progress_hook],
                "windowsfilenames": True,
                "consoletitle": False,
                "merge_output_format": "mp4",
                "socket_timeout": 30,
                "retries": 3,
                "fragment_retries": 5,
                "hls_prefer_ffmpeg": bool(ffmpeg),
            }
            if postprocessors:
                opts["postprocessors"] = postprocessors
            if ffmpeg:
                enable_ffmpeg_hls()
                opts["ffmpeg_location"] = ffmpeg
            if cookies:
                opts["cookiefile"] = cookies
            if qjs:
                opts["js_runtimes"] = {"quickjs": {"path": qjs}}
            if headers:
                opts["http_headers"] = dict(headers)
            return opts

        for index, entry in enumerate(entries, 1):
            if is_cancelled():
                cancelled = True
                break
            title = entry.get("title") or entry.get("url") or ""
            write_progress(
                {
                    "status": "starting",
                    "index": index,
                    "total": total,
                    "title": title,
                    "success": success,
                    "fail": fail,
                }
            )
            try:
                with ffmpeg_child_env():
                    with yt_dlp.YoutubeDL(make_opts(index, entry.get("headers"))) as ydl:
                        ydl.download([entry["url"]])
                success += 1
            except DownloadCancelled:
                cancelled = True
                break
            except Exception as exc:
                fail += 1
                last_error = f"{title}: {exc}"
                failed.append(
                    {
                        "url": entry.get("url"),
                        "title": title,
                        "error": str(exc),
                    }
                )
                log(f"失败：{title} - {exc}")
                log(traceback.format_exc())
                write_progress(
                    {
                        "status": "error_item",
                        "index": index,
                        "total": total,
                        "title": title,
                        "error": str(exc),
                        "last_error": last_error,
                        "success": success,
                        "fail": fail,
                    }
                )
        write_progress(
            {
                "status": "done",
                "cancelled": cancelled,
                "success": success,
                "fail": fail,
                "total": total,
                "last_error": last_error,
                "failed": failed,
            }
        )
    except Exception as exc:
        traceback_text = traceback.format_exc()
        write_progress(
            {
                "status": "error",
                "error": str(exc),
                "traceback": traceback_text,
            }
        )
        log(f"服务错误：{exc}")
        log(traceback_text)
    finally:
        if wake_lock is not None:
            try:
                wake_lock.release()
            except Exception:
                pass
        try:
            service.stopSelf()
        except Exception:
            pass


if __name__ == "__main__":
    main()
