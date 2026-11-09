#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""悬浮嗅探服务：在屏幕上显示一个可拖动的小圆钮。

点击圆钮会打开主 App，由主 App 读取剪贴板并自动解析；长按圆钮关闭服务。
真正的“识别其他 App 当前视频”需要无障碍或录屏权限，这里用更轻的
“复制链接 → 点圆钮”方式，避免过度申请权限。
"""

import time
from pathlib import Path

from jnius import PythonJavaClass, autoclass, java_method

PythonService = autoclass("org.kivy.android.PythonService")
service = PythonService.mService
Context = autoclass("android.content.Context")
WindowManager = autoclass("android.view.WindowManager")
LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
TextView = autoclass("android.widget.TextView")
GradientDrawable = autoclass("android.graphics.drawable.GradientDrawable")
Color = autoclass("android.graphics.Color")
PixelFormat = autoclass("android.graphics.PixelFormat")
Gravity = autoclass("android.view.Gravity")
MotionEvent = autoclass("android.view.MotionEvent")
Build = autoclass("android.os.Build")
BuildVersion = autoclass("android.os.Build$VERSION")
Intent = autoclass("android.content.Intent")
PythonActivity = autoclass("org.kivy.android.PythonActivity")
Handler = autoclass("android.os.Handler")
Looper = autoclass("android.os.Looper")

files_dir = Path(service.getFilesDir().getAbsolutePath())
flag_path = files_dir / "sniffer.flag"
log_path = files_dir / "sniffer.log"
_keep_alive = []


def log(message):
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
    except Exception:
        pass


def dp(value):
    return int(
        value * service.getResources().getDisplayMetrics().density
    )


class TouchListener(PythonJavaClass):
    __javainterfaces__ = ["android/view/View$OnTouchListener"]
    __javacontext__ = "app"

    def __init__(self, window_manager, view, params, on_tap, on_long):
        super().__init__()
        self.wm = window_manager
        self.view = view
        self.params = params
        self.on_tap = on_tap
        self.on_long = on_long
        self.down_raw_x = 0
        self.down_raw_y = 0
        self.start_x = 0
        self.start_y = 0
        self.moved = False
        self.down_at = 0.0

    @java_method(
        "(Landroid/view/View;Landroid/view/MotionEvent;)Z"
    )
    def onTouch(self, view, event):
        action = event.getAction()
        if action == MotionEvent.ACTION_DOWN:
            self.down_raw_x = int(event.getRawX())
            self.down_raw_y = int(event.getRawY())
            self.start_x = int(self.params.x)
            self.start_y = int(self.params.y)
            self.moved = False
            self.down_at = time.time()
        elif action == MotionEvent.ACTION_MOVE:
            dx = int(event.getRawX()) - self.down_raw_x
            dy = int(event.getRawY()) - self.down_raw_y
            if abs(dx) > dp(8) or abs(dy) > dp(8):
                self.moved = True
            self.params.x = self.start_x + dx
            self.params.y = self.start_y + dy
            try:
                self.wm.updateViewLayout(self.view, self.params)
            except Exception:
                pass
        elif action == MotionEvent.ACTION_UP:
            if not self.moved:
                if time.time() - self.down_at > 0.8:
                    self.on_long()
                else:
                    self.on_tap()
        return True


class UiRunnable(PythonJavaClass):
    __javainterfaces__ = ["java/lang/Runnable"]
    __javacontext__ = "app"

    def __init__(self, func):
        super().__init__()
        self.func = func

    @java_method("()V")
    def run(self):
        try:
            self.func()
        except Exception as exc:
            log(f"UI 任务失败：{exc}")


def open_app():
    try:
        intent = Intent(service, PythonActivity)
        intent.putExtra("sniff", True)
        intent.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK
            | Intent.FLAG_ACTIVITY_SINGLE_TOP
        )
        service.startActivity(intent)
        log("点击气泡，已请求打开主 App")
    except Exception as exc:
        log(f"打开主 App 失败：{exc}")


def setup_overlay():
    try:
        window_manager = service.getSystemService(
            Context.WINDOW_SERVICE
        )
        view = TextView(service)
        view.setText("寻")
        view.setTextSize(20.0)
        view.setTextColor(Color.WHITE)
        view.setGravity(Gravity.CENTER)
        drawable = GradientDrawable()
        drawable.setShape(GradientDrawable.OVAL)
        drawable.setColor(Color.rgb(236, 144, 176))
        drawable.setStroke(dp(2), Color.WHITE)
        view.setBackground(drawable)
        view.setPadding(0, 0, 0, 0)

        overlay_type = (
            LayoutParams.TYPE_APPLICATION_OVERLAY
            if BuildVersion.SDK_INT >= 26
            else LayoutParams.TYPE_PHONE
        )
        params = LayoutParams(
            dp(56),
            dp(56),
            overlay_type,
            LayoutParams.FLAG_NOT_FOCUSABLE
            | LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        )
        params.gravity = Gravity.TOP | Gravity.START
        params.x = dp(16)
        params.y = dp(260)

        def on_long():
            try:
                window_manager.removeView(view)
            except Exception:
                pass
            try:
                flag_path.unlink()
            except Exception:
                pass
            log("长按气泡，关闭悬浮嗅探")
            try:
                service.stopSelf()
            except Exception:
                pass

        listener = TouchListener(
            window_manager, view, params, open_app, on_long
        )
        view.setOnTouchListener(listener)
        window_manager.addView(view, params)
        _keep_alive.append(listener)
        _keep_alive.append(view)
        flag_path.write_text("1", encoding="utf-8")
        log("悬浮嗅探已开启")
    except Exception as exc:
        log(f"创建悬浮窗失败：{exc}")
        try:
            service.stopSelf()
        except Exception:
            pass


log("悬浮嗅探服务启动")
main_handler = Handler(Looper.getMainLooper())
ui_runnable = UiRunnable(setup_overlay)
_keep_alive.append(ui_runnable)
main_handler.post(ui_runnable)

# 保持服务进程存活；Android 前台服务会显示常驻通知。
while True:
    time.sleep(1)
