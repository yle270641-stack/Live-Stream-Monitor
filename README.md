# 直播监控

这是一个在 Windows 本机运行的财经直播摘要工具。它在配置的时段检查直播，录制音频，转成逐字稿，生成五段式摘要，然后推送至飞书。

当前 B 站可直接工作。抖音通过本机 Playwright 浏览器检测开播并捕获播放器真实请求的短期 FLV 地址；登录过期时需重新扫码。

## 一键启动

首次使用，按下面顺序操作：

1. 双击 `工具箱.bat`，选择 `1. 安装依赖`（安装 Playwright 与 Chromium）。如有 NVIDIA GPU，再选 `2. 安装 CUDA 依赖` 可加速本地转写。
2. 双击 `登录抖音.bat`：会打开抖音页面，用手机抖音扫描页面二维码。登录成功后直接关闭窗口即可，登录态仅保存在本机 `browser_profile/douyin`。
3. 双击 `启动直播监控.bat`：启动常驻监控。窗口需保持打开。

日常使用只需双击 `启动直播监控.bat`。抖音登录过期时双击 `登录抖音.bat` 重新扫码。其他不常用操作（安装依赖、安装 CUDA、查看状态浮窗）都收在 `工具箱.bat` 里。

抖音登录过期时，再次双击 `登录抖音.bat` 扫码即可。程序不会读取、导出或上传 Cookie、密码或浏览器 profile。

可在主播开播时手工确认抖音取流是否正常：

```powershell
python scripts/douyin_live.py stream --anchor douyin_wending
```

不连接真实直播的安全模拟：

```powershell
python scripts/simulate.py
```

## 配置

真实配置为 `config/anchors.json`，其中包含飞书 Webhook，不能提交到 Git。模型配置写在项目根目录的 `.env` 文件中：

```text
LLM_API_KEY=你的中转站Key
LLM_MODEL=模型名称
LLM_BASE_URL=https://你的中转站地址/
```

Portdan 可填写 `https://portdan.com/`；程序会自动补上 `/v1/chat/completions`。模型名称必须使用 Portdan 控制台中显示的可用模型名。

转写默认使用本地 `faster-whisper`，音频不会上传飞书；首次运行会下载模型。当前已默认配置为 NVIDIA CUDA 的 `float16` 模式。首次使用前运行 `安装CUDA依赖.bat` 安装 CUDA 运行库。可在 `.env` 调整 `WHISPER_MODEL`：`tiny` 约 150 MB、`small` 约 500 MB、`medium` 约 1.5 GB。旧的 `lark-cli` 配置仅保留作备用，不再是必需条件。

程序会自动读取 `.env`；也支持用 PowerShell 环境变量覆盖它。

没有配置 `LLM_API_KEY` 时，程序仍会生成保守的逐字稿摘录，但不会假装它是模型摘要。

## 运行

先做一次不录制的窗口检查：

```powershell
python scripts/watcher.py --once
```

对当前在播的 B 站主播做 30 秒端到端测试：

```powershell
python scripts/watcher.py --once --max-seconds 30
```

常驻运行（未开播时默认每 120 秒轮询一次）：

```powershell
python scripts/watcher.py --daemon
```

正式运行不传 `--max-seconds`，每位主播按 30 分钟一段录制；每段完成后独立转写、摘要并单独推送到飞书，不同主播不会混在一起。直播未结束时也会持续收到每段摘要，直播结束后不会凭空补写没有录到的内容。常驻模式还会立即并每 30 分钟推送一条运行状态消息；异常时标题会改为“部分异常”。失败任务会退避后重试，避免每轮重复录制。状态保存在 `logs/state.json`。建议用 Windows 任务计划程序在登录时运行上述常驻命令。

监控运行期间按 `F9`，会立即结束当前正在录音的主播片段，转写并生成“即时摘要”推送到飞书；没有正在录音的主播时按键不会生成空摘要。

## 依赖和限制

录音、B 站查询、飞书推送和本地转写均已接入；首次使用本地 ASR 时需要下载模型，并需要预留 CPU 时间和磁盘空间。
