# 直播监控

一个在 Windows 本机运行的直播音频监控与摘要工具。它可按时间窗口检查抖音和 Bilibili 直播，使用 FFmpeg 录制音频，通过 faster-whisper 本地转写，调用 OpenAI 兼容接口生成摘要，并可推送到飞书群机器人。

> 本项目仅用于处理你有权访问和录制的内容。使用前请遵守直播平台条款、著作权规则和所在地法律。生成的财经摘要仅作客观转述，不构成投资建议。

## 功能

- Bilibili 无登录开播检测与取流
- 抖音 Playwright 本地登录、开播检测与临时流地址捕获
- FFmpeg 分段录音，支持断流恢复和 `F9` 提前结束当前片段
- faster-whisper 本地转写，音频无需上传到第三方 ASR
- OpenAI 兼容接口生成五段式摘要，无 Key 时生成保守摘录
- 飞书机器人推送、失败重试、运行心跳和本地产物清理

## 环境要求

- Windows 10/11
- Python 3.11 或 3.12
- FFmpeg 和 FFprobe（可通过 `winget install Gyan.FFmpeg` 安装）
- 抖音功能需要 Playwright 浏览器和一次手机扫码登录
- 可选：NVIDIA GPU，用于加速 faster-whisper

## 快速开始

首次使用按下面顺序操作，整个流程可以先不配置任何密钥：

```powershell
git clone <你的仓库地址>
cd <仓库目录>
Copy-Item config/anchors.example.json config/anchors.json
# .env.example 是仓库内的公开模板；真实密钥只写入本地 .env
Copy-Item .env.example .env
```

编辑 `config/anchors.json`，替换示例主播的 `sec_uid`、`mid`、`room_id` 和监控时间段。敏感值写入 `.env`，不要写进示例配置或提交到 Git。

随后双击 `工具箱.bat`：

1. 选择 `1` 创建虚拟环境并安装依赖。
2. 如使用 NVIDIA GPU，可选择 `2` 安装 CUDA Python 运行库，并在 `.env` 设置 `WHISPER_DEVICE=cuda`、`WHISPER_COMPUTE_TYPE=float16`。
3. 使用抖音时选择 `3`，扫码登录后关闭浏览器。
4. 选择 `5` 检查配置、主播字段和 FFmpeg 是否可用。
5. 双击 `启动直播监控.bat` 启动常驻监控。

如果只想确认环境是否正常，完成第 1、2 步后选择工具箱的 `5`（检查配置和运行环境），再选择 `6`（运行离线模拟）。离线模拟不会访问直播平台、模型接口或飞书，适合首次安装和提交 Issue 前自检。

也可以直接运行：

```powershell
.\.venv\Scripts\python.exe scripts\watcher.py --once
.\.venv\Scripts\python.exe scripts\simulate.py
.\.venv\Scripts\python.exe scripts\check_config.py
.\.venv\Scripts\python.exe scripts\watcher.py --daemon
```

`--once` 只检查一轮；`simulate.py` 默认完全离线，不连接直播、不调用模型、不推送飞书，产物写入 `logs/simulation/`。可用 `--output-dir` 隔离测试目录；需要验证模型接口时显式运行 `simulate.py --use-llm`；`--daemon` 启动常驻监控。

## 运行流程

```text
直播平台 -> 开播检测 -> FFmpeg 录音 -> faster-whisper 转写
                                      -> 本地摘要 -> 可选飞书推送
```

录音、逐字稿、摘要和运行日志默认只写入本机。未配置模型密钥时仍会生成本地保守摘录；未配置飞书 Webhook 时不会发送网络请求。项目不会自动交易，也不会替你下单。

## 配置

真实配置文件为 `config/anchors.json`，格式参考 `config/anchors.example.json`。`tools.ffmpeg` 和 `tools.ffprobe` 默认从 `PATH` 解析，也可以改为本机绝对路径。监控时间使用本机时区，支持跨午夜窗口，例如 `["23:00", "01:00"]`。

修改配置后建议先离线检查；该命令不会访问直播平台、模型接口或飞书：

```powershell
.\.venv\Scripts\python.exe scripts\check_config.py
```

常用环境变量：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `LLM_API_KEY` | OpenAI 兼容接口密钥 | 空，使用本地摘录 |
| `LLM_BASE_URL` | Chat Completions 接口或 API 根地址 | OpenAI 接口 |
| `LLM_MODEL` | 摘要模型名 | `gpt-4o-mini` |
| `FEISHU_WEBHOOK` | 飞书自定义机器人 Webhook | 空，不推送 |
| `WHISPER_MODEL` | faster-whisper 模型 | `small` |
| `WHISPER_DEVICE` | `auto`、`cpu` 或 `cuda` | `auto`，自动检测可用 GPU |
| `CLEANUP_AFTER_PUSH` | 推送成功后删除录音和逐字稿 | `true` |

环境变量优先于配置文件中的飞书 Webhook。`WHISPER_DEVICE=auto` 会检查 CTranslate2 的 CUDA 能力；只有运行时确实可用时才使用 GPU，否则回退 CPU。显式设置 `cpu` 或 `cuda` 可覆盖自动判断。`.env`、真实主播配置、浏览器登录态、录音、逐字稿和日志均已被 `.gitignore` 排除。

## 数据目录

- `recordings/`：直播录音
- `transcripts/`：逐字稿与摘要
- `logs/`：运行状态、错误和待推送内容
- `browser_profile/`：抖音本地登录态

以上目录可能含敏感内容，不应提交或分享。默认保留期由 `retention_days` 控制。

## 常见问题

- **检查提示缺少 FFmpeg**：安装 FFmpeg 后重新打开 PowerShell，确认 `ffmpeg -version` 和 `ffprobe -version` 可执行；也可以在 `config/anchors.json` 的 `tools` 中填写完整路径。
- **抖音检测不到直播**：先在工具箱选择 `3` 完成扫码登录，再确认 `browser_profile/` 未被清理；该目录包含登录态，不要上传。
- **没有飞书消息**：先查看 `logs/pending_push_*.txt` 和 `logs/errors.log`。Webhook 留空时，摘要只保存在 `transcripts/`，这是预期行为。
- **模型下载或转写很慢**：首次运行会下载 faster-whisper 模型；可先将 `WHISPER_DEVICE=cpu`，确认流程后再安装 CUDA 组件。
- **监控窗口反复重启**：查看 `logs/watcher_console.log` 和 `logs/state.json`，先运行工具箱的 `5` 检查配置，不要同时启动多个 watcher。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `scripts/watcher.py` | 常驻监控主程序 |
| `scripts/check_config.py` | 不联网的配置和依赖检查 |
| `scripts/simulate.py` | 不联网的端到端模拟 |
| `scripts/manage_anchors.py` | 添加或删除主播配置 |
| `config/anchors.example.json` | 可提交的主播配置模板 |
| `.env.example` | 可提交的密钥和运行参数模板 |
| `工具箱.bat` | Windows 菜单入口 |

真实的 `.env`、`config/anchors.json`、浏览器登录态和运行产物均不会提交到 Git。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q scripts tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check scripts tests
```

GitHub Actions 会在 Python 3.11 和 3.12 上检查公开示例配置、执行静态检查、编译和单元测试。

## 许可证

[MIT License](LICENSE)
