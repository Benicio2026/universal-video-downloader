# 万能视频下载器 · Universal Video Downloader

> 一个自己写的 Android 视频下载器：Kivy 界面 + [yt-dlp](https://github.com/yt-dlp/yt-dlp) 引擎。
> 目标不是只下油管，而是覆盖浏览器嗅探插件（如猫抓）能处理的绝大多数站点。

![界面截图](screenshot.png)

## 它是什么

- 一个可以直接安装的 Android APK（通过 GitHub Actions 免费构建）
- 手机上**不需要** Termux、Python、root、FFmpeg 或任何其他 App
- 粘贴视频页面链接，yt-dlp 负责解析和下载
- 支持 yt-dlp 收录的一千多个站点：YouTube、Bilibili、X/Twitter、TikTok、Instagram、Vimeo、微博、部分新闻/教育站点等；未收录站点由通用提取器兜底

## 和猫抓的区别

猫抓是浏览器扩展，靠嗅探页面里的媒体请求来抓视频；本项目不做嗅探，而是把链接交给 yt-dlp，由它解析播放器、处理签名、下载分片、再用 FFmpeg 合并。

- 好处：覆盖面更广，不依赖浏览器，不会被页面脚本轻易挡住
- 代价：没有"在网页里点一下就抓"的体验，需要复制链接或从浏览器分享过来

## 功能

- 粘贴链接 / 一键读取剪贴板
- 画质选择：最佳、1080p 及以下、720p 及以下、仅音频
- 下载进度、速度、剩余时间
- 代理设置（适合需要代理访问 YouTube 的场景）
- 保存到公共 `Download` 目录（需授予"所有文件访问"权限）
- 日志面板，出错时能看到 yt-dlp 的原始信息
- 全中文界面，自带中文字体，不依赖系统字体

## 当前版本与限制（v0.1.0）

这是第一个可安装版本，重点是把「链接 → 解析 → 下载 → 落盘」跑通：

- ✅ yt-dlp 解析与下载
- ✅ 单文件格式（音视频合一）
- ✅ 代理、日志、取消、进度
- ⏳ **FFmpeg 尚未内置**：高清 DASH 站点（如 YouTube 1080p+）可能只能选到较低的单文件画质；MP3 转码暂不可用
- ⏳ YouTube 的 JS challenge 在没有 JS 运行时的情况下可能进一步限制可选画质；后续版本会评估内置轻量运行时
- ⏳ 登录 / 会员内容（Cookie）暂不支持
- ⏳ 播放列表默认只下载当前视频
- ⏳ App 退到后台后下载可能被系统暂停
- ❌ DRM 强加密站点（Netflix、Disney+ 等）不支持，这是引擎层面的限制

## 安装

1. 在仓库的 **Releases** 页面下载 `*-debug.apk`
2. 手机上允许「安装未知来源应用」
3. 首次启动授予存储权限；Android 11+ 需要到系统设置里授予「所有文件访问」
4. 需要访问 YouTube 时，在「代理」栏填写代理地址，例如 `http://127.0.0.1:7890`

> APK 预计 50–90 MB（包含 Python 运行时和中文字体）。
>
> 华为 / 荣耀等机型如果开启了「纯净模式」，需要在系统设置里允许安装外部来源应用。
>
> 当前 APK 只构建 `arm64-v8a`（近几年的主流安卓手机都是该架构）。如果你的手机较老、安装时提示 ABI 不兼容，告诉我，我再加上 `armeabi-v7a`。

## 使用

1. 在浏览器里复制视频页面链接
2. 打开 App，点「粘贴」
3. 选择画质，点「开始下载」
4. 下载完成后到 `Download/UniversalVideoDownloader` 查看文件

## 支持的站点

yt-dlp 的站点列表见：
<https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md>

只要某个站点在列表里，或者能被通用提取器识别，这个 App 就有机会下载。DRM 保护的流媒体不在支持范围内。

## 构建 APK

### 方式一：GitHub Actions（推荐，免费）

公开仓库的 GitHub Actions 标准 runner 免费。推送 `v*` 标签会自动构建并创建 Release：

```bash
git tag v0.1.0
git push origin v0.1.0
```

也可以到 Actions 页面手动运行 `Build Android APK`。

### 方式二：本地 Buildozer（Linux / WSL）

Windows 不能直接运行 Buildozer，需要 Linux 或 WSL：

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

```
universal-video-downloader/
├── main.py                    # Kivy 界面 + 下载逻辑
├── app.kv                     # 界面布局与样式
├── buildozer.spec             # Android 打包配置
├── scripts/fetch_font.py      # 构建前下载中文字体
├── assets/fonts/              # 字体（构建时下载，不入库）
├── requirements.txt           # 桌面端调试依赖
├── screenshot.png             # 界面截图
├── LICENSE                    # MIT
├── THIRD_PARTY_NOTICES.md
└── .github/workflows/build-apk.yml
```

## 桌面端调试

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python main.py
```

Windows 上会自动使用系统自带的中文字体（微软雅黑）进行调试；Android 上使用随 APK 打包的 Noto Sans CJK。

## 技术栈与致谢

- [Kivy](https://kivy.org/) — MIT，跨平台 Python GUI
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Unlicense，解析与下载引擎
- [python-for-android](https://github.com/kivy/python-for-android) / [Buildozer](https://github.com/kivy/buildozer) — 打包 APK
- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) — SIL Open Font License 1.1，中文字体
- FFmpeg — 规划中，尚未包含在 v0.1.0

本项目的界面、交互和打包脚本为原创；下载能力完全来自 yt-dlp。

## 免费说明

- GitHub Actions 公开仓库构建：免费
- GitHub Releases 分发 APK：免费
- Debug 签名 APK：免费，不上架 Google Play（避免 $25 开发者费）
- 无广告、无内购、无遥测
- 唯一可能产生费用的是你自己的代理/VPN 线路，这部分与本项目无关

## 免责声明

- 本项目与 YouTube / Google / 哔哩哔哩等站点无任何关联
- 请只下载你有权保存的内容，遵守目标网站的服务条款和你所在地区的法律法规
- 请勿用于侵权、二次分发或商业用途
- 本项目不绕过 DRM，也不托管任何视频内容

## License

MIT，见 [LICENSE](LICENSE)。第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
