#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android 前台下载服务：由 p4a 启动，在独立进程中执行下载。

App 写入 service_job.json，本服务读取后下载，持续写入
service_progress.json；App 关闭后服务仍可继续。
"""

import json
import re
import time
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled
from jnius import autoclass

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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
        job = json.loads(job_path.read_text(encoding="utf-8"))
        entries = job.get("entries") or []
        quality = job.get("quality") or "最佳画质（自动）"
        outdir = Path(job.get("outdir") or (files_dir / "Downloads"))
        outdir.mkdir(parents=True, exist_ok=True)
        ffmpeg = job.get("ffmpeg")
        cookies = job.get("cookies")
        total = len(entries)
        success = 0
        fail = 0
        cancelled = False

        def is_cancelled():
            return cancel_path.exists()

        def make_opts(index):
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
                "progress_hooks": [progress_hook],
                "windowsfilenames": True,
                "consoletitle": False,
                "merge_output_format": "mp4",
            }
            if postprocessors:
                opts["postprocessors"] = postprocessors
            if ffmpeg:
                opts["ffmpeg_location"] = ffmpeg
            if cookies:
                opts["cookiefile"] = cookies
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
                with yt_dlp.YoutubeDL(make_opts(index)) as ydl:
                    ydl.download([entry["url"]])
                success += 1
            except DownloadCancelled:
                cancelled = True
                break
            except Exception as exc:
                fail += 1
                log(f"失败：{title} - {exc}")
                write_progress(
                    {
                        "status": "error_item",
                        "index": index,
                        "total": total,
                        "title": title,
                        "error": str(exc),
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
            }
        )
    except Exception as exc:
        write_progress({"status": "error", "error": str(exc)})
        log(f"服务错误：{exc}")
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
