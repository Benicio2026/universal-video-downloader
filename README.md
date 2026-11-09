# 万能视频下载器

[![Build Android APK](https://github.com/Benicio2026/universal-video-downloader/actions/workflows/build-apk.yml/badge.svg)](https://github.com/Benicio2026/universal-video-downloader/actions/workflows/build-apk.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Android 视频下载 App。界面用 Kivy 写，下载交给 [yt-dlp](https://github.com/yt-dlp/yt-dlp)。支持 YouTube、Bilibili、X、TikTok 等一千多个站点。

<p align="center">
  <img src="screenshot.png" width="320" alt="界面截图">
</p>

## 功能

- 粘贴链接下载
- 画质：最佳 / 1080p / 720p / 仅音频
- 显示进度、速度、剩余时间，可取消
- 代理设置
- 保存到公共 Download 目录
- 中文界面，内置中文字体
- 无广告、无内购

## 安装

1. 从 [Releases](https://github.com/Benicio2026/universal-video-downloader/releases) 下载 APK
2. 允许安装未知来源应用
3. 首次启动授予存储权限。Android 11 及以上需要到系统设置里打开“所有文件访问”
4. 需要访问 YouTube 时，在“代理”栏填写代理地址

华为、荣耀机型如果开启了纯净模式，需要先允许安装外部来源应用。当前 APK 只包含 `arm64-v8a`，近几年的主流手机都是这个架构。

## 使用

1. 在浏览器里复制视频页面链接
2. 打开 App，点“粘贴”
3. 选择画质，点“开始下载”
4. 下载完成后到 `Download/UniversalVideoDownloader` 查看文件

浏览器插件（比如猫抓）靠在页面里嗅探视频请求。这个 App 把链接交给 yt-dlp 解析，支持 yt-dlp 收录的站点；使用时需要先复制链接，少了在网页里直接点一下的步骤。

## 支持的站点

完整列表见 yt-dlp 的 [supportedsites.md](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)。Netflix、Disney+ 这类 DRM 保护的流媒体不在支持范围内。

## 已知限制

- 没有内置 FFmpeg，目前只能下载音视频合一的单文件格式。YouTube、B站的高清 DASH 流需要合并音视频，暂时下不到最高画质；MP3 转码也不可用。
- 暂不支持 Cookie 登录、会员内容、后台下载、播放列表批量下载。
- YouTube 的 JS challenge 在手机上可能限制部分画质，后续版本再处理。
- 当前只构建了 `arm64-v8a`，32 位老手机无法安装。

## 自己构建

GitHub Actions 会在推送 `main` 或 `v*` 标签时构建 APK。公开仓库的 Actions 免费，构建和 Releases 分发都不产生费用。

```bash
git tag v0.1.0
git push origin v0.1.0
```

本地构建需要 Linux 或 WSL，Windows 不能直接运行 Buildozer：

```bash
sudo apt install -y git zip unzip openjdk-17-jdk \
  autoconf libtool pkg-config zlib1g-dev \
  libncurses5-dev libncursesw5-dev libtinfo5 \
  cmake libffi-dev libssl-dev libltdl-dev
python3 -m pip install --user buildozer cython
python3 scripts/fetch_font.py
buildozer -v android debug
```

产物在 `bin/` 目录。

## 项目结构

```text
universal-video-downloader/
├── main.py                    # Kivy 界面和下载逻辑
├── app.kv                     # 界面布局
├── buildozer.spec             # Android 打包配置
├── local_recipes/kivy/        # Kivy recipe override（去掉 requests 依赖）
├── scripts/fetch_font.py      # 构建前下载中文字体
├── assets/fonts/              # 字体和许可证（字体构建时下载）
├── icon.png
├── screenshot.png
├── requirements.txt
├── THIRD_PARTY_NOTICES.md
└── .github/workflows/build-apk.yml
```

## 常见问题

**安装时被拦截？** 允许安装未知来源应用；华为、荣耀机型先关闭纯净模式。

**下载报 403 或要求登录？** 这个版本没有 Cookie 支持，部分站点会失败，等下个版本。

**下载不到 4K，或者下完打不开？** 这个版本没有 FFmpeg 合并，YouTube 等站点的高清流需要合并音视频，建议选 1080p 及以下。

**下载速度慢？** 在代理栏填写可用的代理地址。

**文件保存在哪？** 默认在 `Download/UniversalVideoDownloader`。如果没有授予“所有文件访问”，会保存到 App 私有目录，具体路径显示在界面上。

遇到问题可以在 [Issues](https://github.com/Benicio2026/universal-video-downloader/issues) 里反馈。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：解析和下载
- [Kivy](https://kivy.org/)：界面
- [python-for-android](https://github.com/kivy/python-for-android)、[Buildozer](https://github.com/kivy/buildozer)：APK 打包
- [Noto Sans CJK](https://github.com/notofonts/noto-cjk)：中文字体

## 许可

MIT，见 [LICENSE](LICENSE)。第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 免责声明

请只下载你有权保存的内容，遵守目标网站的服务条款和当地法律。这个项目不绕过 DRM。
