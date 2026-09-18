# 财经直播自动监看工具 · 交接文档（HANDOFF for Codex）

> 你将接手一个「自动监看财经直播 → 只录音频 → 转文字 → 结构化纪要 → 飞书群推送」的 Windows 本机工具。
> 前一阶段在**豆包（Doubao）agent 环境**里完成了可行性验证和部分脚本；现在目标是**脱离豆包、做成在用户电脑上独立常驻运行的程序**。本文档包含全部已验证事实，请勿重复踩坑。

---

## 1. 项目目标

- 每天自动监看 **2 个抖音直播间 + 1 个 B站直播间**（财经/股票主播）。
- **只录音频、不录画面**（直播没有现成字幕，必须“录声音 → 语音识别成文字”）。
- 下播后把整场转成逐字稿，再由 LLM 提炼成**五段式纪要**，通过**飞书自定义群机器人 Webhook** 推送到用户的飞书群；每晚再发一条三场汇总。
- 运行形态：**Windows 本机常驻/计划任务**，直播时段电脑开机联网即可，不依赖豆包客户端在线。

### 五段式纪要结构（固定）
1. 一句话核心观点
2. 大盘 / 仓位判断
3. 看好与看空板块
4. 提到的个股与操作（**必须带逐字稿时间点**）
5. 风险提示
- 头部：主播名 · 直播起止时间 · 时长；尾部固定：`仅作客观转述，不构成投资建议。逐字稿：<minute_url 或本地路径>`
- 只依据逐字稿，**不得编造**逐字稿里没有的观点、数字、个股。

---

## 2. 三个目标主播（已锁定，勿再猜）

| key | 平台 | 昵称 | 认证 | 标识 | 开播时间 |
|---|---|---|---|---|---|
| `douyin_caicaishuo` | 抖音 | 股市才才说 | 江海证券投资顾问 | sec_uid=`MS4wLjABAAAA5vRhYjY2XGcOhPXQ9DPiBF-sbRRk2R5sOnlTbC8GLRVo6R_mdWQ-_khuSPz6P_VX`，抖音号 30642358441 | 用户标注约 **21:00**（主页未写明，待用户最终确认） |
| `douyin_wending` | 抖音 | 文鼎（文说股市） | 利多星证券投资顾问 | sec_uid=`MS4wLjABAAAAL_p5dizu5Fh-nc-u6ViPLZAk72Hea8StZfH2Ck-s-ND0eRfuF9KnGlqQ8ek1ng35`，抖音号 95892981226 | 主页写明 **早 7:30 / 晚 19:30 / 周日 10:00** |
| `bili_luojige` | B站 | 逻辑哥复盘笔记 | — | 用户 mid=`433280310`，直播间 room_id=`1785947366`，https://live.bilibili.com/1785947366 | 标题显示“下午看盘”，具体时间待确认 |

以上已写入 `config/anchors.json`（含轮询窗口 poll_windows、采样参数、飞书 webhook）。

---

## 3. 当前进度：哪些已验证打通，哪些还没做

| 环节 | 状态 | 说明 |
|---|---|---|
| ffmpeg 安装、只录音频 | ✅ 已验证 | ffmpeg 9.0.1，命令/参数见 §5，抖音、B站同为 FLV 均可录 |
| 三主播身份与 ID | ✅ 已锁定 | 见 §2 |
| 抖音“登录态→拿流地址→录音” | ⚠️ **仅在豆包受控浏览器里验证过** | 已证明路径可行，但用的是豆包专属浏览器栈，**Codex 必须用 Playwright 等独立复现**（见 §6-A） |
| B站查状态 / 取流 | ✅ 脚本已写并验证 | `scripts/bili_live.py`，公开接口、无需登录 |
| 录音脚本 | ✅ 已自检 | `scripts/record_audio.py` |
| 语音转写（ASR） | ⚠️ 用豆包内置 lark-cli+飞书妙记验证通过 | **Codex 需判断能否外部复用，否则替换 ASR**（§6-B） |
| 飞书机器人推送 | ✅ 已真实推送成功 | webhook 已配置，`scripts/feishu_push.py` |
| LLM 五段式提炼 | ❌ 之前由豆包模型直接做 | **Codex 需接 LLM API**（§6-C） |
| 定时调度 | ❌ 未建成 | 豆包 cron 最小间隔 900 秒且依赖豆包在线；**改用 Windows 任务计划/常驻进程**（§6-D） |
| 对“目标主播本人”真实试录 | ❌ 未做（验证时用的是其他在播直播间） | 需在开播窗口对 3 个主播各录 ~120 秒跑通 |
| 编排主程序 / 防重 / 清理 / 正式每日任务 | ❌ 未做 | 见 §6-E、§7 |

---

## 4. 现有文件（已迁到本目录，均已自检，除标注外可直接用）

```
直播监控/
├─ config/anchors.json      # 主播、工具绝对路径、飞书webhook、录音/转写/保留参数
├─ scripts/
│  ├─ common.py             # 公共：配置加载、工具路径解析、跑命令、JSON截取、日志（纯标准库）
│  ├─ bili_live.py          # B站 status / playurl（已验证）
│  ├─ record_audio.py       # ffmpeg 只录音频为 16k/单声道/64k mp3（已验证）
│  ├─ transcribe.py         # lark-cli 三步转写+轮询（豆包环境可用，外部待验证）
│  ├─ feishu_push.py        # 飞书自定义机器人推送；未配 webhook 时落盘不丢消息（已验证）
│  └─ RUNBOOK.md            # 豆包版操作步骤（可参考，里面 bu 浏览器部分豆包专属）
├─ recordings/ transcripts/ logs/   # 产物目录（空）
└─ HANDOFF.md（本文件）
```
> `common.py` 的项目根用 `__file__` 自动推导，**迁移目录无需改路径**；但 `config/anchors.json -> tools` 里是系统级绝对路径，换机/重装要更新。

### 工具绝对路径（当前机器，已写入 config）
- ffmpeg / ffprobe：`C:/Users/Yule2/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.1-full_build/bin/ffmpeg.exe`（同目录 ffprobe.exe）。winget 安装后**新开的进程可能没继承 PATH**，脚本里优先用绝对路径。
- lark-cli：`C:/Users/Yule2/AppData/Local/Doubao/User Data/Default/sandbox_envs_dir/envs/8ab491e9-8e4f-4b5c-9e50-92bdf33521b9/override_dlcs/lark-cli.exe`（v1.0.93，**位于豆包运行时目录，外部能否调用需实测**）。
- 当前 `python` 是豆包内置 **Python 3.14.7（过新，很多 C 扩展 wheel 不全）**。Codex 独立实现请自建 **Python 3.11/3.12 venv**，不要依赖 3.14。

---

## 5. 已验证的关键技术事实（直接采用，勿重复试错）

### 5.1 抖音（最难，已摸清机制）
- 抖音**没有可直接抓的字幕**；未开播时主播主页数据里 `roomId=0`、没有固定 web_rid，**必须在其开播后**才能拿到直播间号与流地址。
- 在“已登录的浏览器”里打开直播间 `https://live.douyin.com/<web_rid>`，播放器会发起真实拉流请求，URL 形如：
  `https://<随机>.ctcdn.com.cn/pull-flv-t95.douyincdn.com/stage/stream-xxx.flv?reqhost=...&expire=...&sign=...&biz_quality=ld&biz_protocol=flv`
  - 该 URL 自带签名，`expire` 约 7 天有效；**不需要自己算签名**，直接抓播放器实际请求的 URL 即可。
  - 豆包里是用受控浏览器的 network 事件筛 `douyincdn.com` 且含 `.flv?` 得到的；**Codex 用 Playwright 的 response/request 监听等价实现**。
- ffmpeg 拉这条 flv、只录音频（实测成功，12 秒/5 秒均 OK，video:0KiB）：
  ```
  ffmpeg -y -rw_timeout 20000000 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 \
    -user_agent "<浏览器UA>" -headers "Referer: https://live.douyin.com/\r\n" \
    -i "<flv_url>" -vn [-t 秒数; 整场省略] -ac 1 -ar 16000 -acodec libmp3lame -b:a 64k out.mp3
  ```
- 抖音取流**需要登录态**；登录态会过期（数天~数周），过期页面会弹登录二维码，需要引导用户重新扫码，**不得读取/导出 cookie 明文、不存密码**。

### 5.2 B站（公开接口，无需登录）
- 查开播状态：`GET https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid=<用户mid>`
  - **参数必须是 `mid`（433280310），传 room_id 会返回 -400。**
  - 返回 `data` 里状态字段是**驼峰 `liveStatus`**（0 未播 / 1 开播 / 2 轮播），注意和下面接口的下划线命名区别。
- 取流地址：`GET https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo?room_id=1785947366&protocol=0,1&format=0,1,2&codec=0,1&qn=10000&platform=web`（带 UA + `Referer: https://live.bilibili.com/1785947366`）
  - 未开播时 `data.playurl_info` 为 null（接口仍 code=0）。
  - 完整流地址拼接：遍历 `playurl.stream[].format[].codec[]`，对每个 `url_info[]`：**`url_info.host + codec.base_url + url_info.extra`**；优先 format=flv、protocol=http_stream、codec=avc。
- 录音同样用 §5.1 的 ffmpeg 命令，Referer 换成直播间页。

### 5.3 飞书自定义群机器人（已通）
- `POST <webhook>`，body `{"msg_type":"text","content":{"text":"标题\n\n正文"}}`，成功返回 `{"code":0,"msg":"success"}`（也带 StatusCode:0）。已真实发通过。
- webhook 地址已存 `config/anchors.json -> feishu_webhook`，**属敏感信息，勿提交到公开仓库**。

### 5.4 lark-cli + 飞书妙记转写（豆包环境已验证，供外部复用参考）
三步（均 `--format json`，输出会混日志行，需截取首个 `{...}`）：
1. 在**音频所在目录**执行 `lark-cli drive +upload --file ./xxx.mp3 --format json` → `data.file_token`（拒绝绝对路径/外部路径，所以要 cwd 到音频目录、用 `./文件名`）。
2. `lark-cli minutes +upload --file-token <token> --format json` → `data.minute_token`，妙记 URL `https://www.feishu.cn/minutes/<token>`。
3. 轮询 `lark-cli vc +notes --minute-tokens <token> --output-dir . --format json`（cwd=输出目录），直到 `data.notes[0].artifacts.transcript_file` 指向的 `transcript.txt` 落盘；短音频约 15 秒内，长音频需数分钟，按 15s 间隔轮询、上限放宽。逐字稿带时间戳/说话人/关键词。

### 5.5 其它
- 音频统一 **16kHz / 单声道 / 64kbps mp3**（体积小、适配 ASR）；一场 2 小时约几十 MB。
- 豆包内置定时任务最小执行间隔 **900 秒**（`*/10` 分钟被拒）——Codex 自主调度不受此限。

---

## 6. Codex 要完成的核心工作：替换 4 个“豆包耦合”，再做编排

### A. 抖音取流（最高优先，最大工作量）
用 **Playwright（Python，持久化用户数据目录 launch_persistent_context）** 复现：
1. 首次运行打开 `https://live.douyin.com`，让用户**扫码登录一次**，登录态保存在本地 browser profile（之后复用，过期再扫）。
2. 给定主播 sec_uid：开播窗口内打开 `https://www.douyin.com/user/<sec_uid>`，判断是否在播（开播时主页出现“直播中”入口，href 含 `live.douyin.com/<web_rid>`；或监听其 XHR 里 roomId 由 0 变非 0）。
3. 打开直播间页，用 `page.on("response"/"request")` 捕获 URL 含 `douyincdn.com` 且 `.flv?` 的拉流地址（去重、取第一个），交给 `record_audio.py` 录音。
4. 健壮性：reload 重抓最多 2 次；登录二维码出现时暂停并提示用户扫码；抓不到要**显式报错**，不许静默。
- 备选：成熟开源抖音直播录制项目（如基于 streamlink/ffmpeg 的 douyin live recorder、f2 等）可评估，但要自行处理 cookie 与失效更新；优先 Playwright 自控，最透明可控。

### B. ASR 转写（二选一，先试低成本）
- 方案 1（最省事）：直接调用 §4 的 **lark-cli.exe 绝对路径**，先在普通终端验证 `lark-cli --version` 与三步上传是否仍带登录态；可用就保留 `transcribe.py`。
- 方案 2（完全独立）：本地 **faster-whisper**（在 3.11/3.12 venv，small/medium 模型，中文，CPU 可跑、长音频分段），或接云端 ASR API。注意 2~3 小时音频的分段与耗时。

### C. LLM 五段式提炼
- 接一个可用的聊天模型 API（密钥由用户提供，从环境变量/本地配置读取，勿硬编码、勿提交）。
- 输入逐字稿，system prompt 约束输出严格按 §1 五段式、只引用逐字稿内容、个股带时间点、不给买卖指令、末尾加免责声明。建议同时把逐字稿保存为本地 .txt（或妙记链接）。

### D. 调度（脱离豆包）
- 推荐：一个**常驻 Python 主程序**（或 APScheduler），按 `config.poll_windows` 在窗口期内每 1~3 分钟轮询开播状态；用 **Windows 任务计划程序**设置“登录时自启动 / 断电重启自启”。
- 电脑需在直播时段开机联网；建议把电源设为“闲置/合盖不睡眠”。

### E. 编排主程序与工程化
- 串联：检测开播 →（抖音 Playwright / B站 HTTP）取流 → `record_audio.py`（整场用 `--seconds 0` 录到下播）→ ASR 逐字稿 → LLM 五段式 → `feishu_push.py` 单场纪要；每晚固定时间合并三场发汇总。
- **状态文件** `logs/state.json`：记录每个主播当天是否已录/已推，防重复（替代豆包版 selftest_done.json）。
- **失败必须可见**：取流/录音/转写/推送任一失败都向飞书发告警，说明环节与原因；未开播只写日志、不发空纪要。
- **磁盘清理**：按 `retention_days=7` 清理旧音频/逐字稿。
- 日志统一写 `logs/`。

---

## 7. 建议的目标架构与里程碑

目标架构（独立常驻，不依赖豆包）：
```
Windows 任务计划(开机自启) -> 主进程 scheduler
  -> 窗口期轮询每个主播是否开播
      -> B站: bili_live.py(HTTP)           抖音: Playwright持久化profile抓flv
      -> record_audio.py 只录音频(录到下播)
      -> ASR 转写(lark-cli 或 faster-whisper)
      -> LLM 五段式纪要
      -> feishu_push.py 推送 + state.json 防重 + logs
  -> 每晚汇总一次; 失败告警; 定时清理
```
建议里程碑：
1. **M1 复现抖音取流**：Playwright 登录 + 对任一在播间抓到 flv 并录 30 秒音频（最高风险，先做）。
2. **M2 定 ASR**：验证 lark-cli 外部可用性或落地 faster-whisper，跑通“音频→逐字稿”。
3. **M3 单场闭环**：对 1 个主播做到“开播→录音→逐字稿→五段式→飞书收到”。
4. **M4 三主播 + 调度 + 防重/告警/清理**，进入 1~2 天观察期。
5. **M5 正式上线**，替换为每日任务。

---

## 8. 运行前提、合规与安全
- Windows 本机、直播时段开机联网；抖音登录态过期需用户重新扫码（程序要能提示）。
- 录制内容**仅供用户个人使用，勿公开传播**（涉及主播版权与平台条款）；工具不下单、不输出买卖指令。
- 纪要仅客观转述，**不构成投资建议**。
- webhook、LLM/ASR 的 API Key、浏览器登录 profile 都是敏感物：本地保存、**不提交公开仓库**（建议生成 .gitignore）。

## 9. 验收标准
- 三个主播在开播后均能：自动录音 → 非空逐字稿 → 五段式纪要 → 飞书群收到（B站应最稳，两个抖音为重点验证对象）。
- 连续观察期内，**每场都有“纪要”或“明确失败原因告警”**，不允许无声失败。
- 纪要中的个股/观点可回溯到逐字稿时间点。

## 10. 仍需向用户确认的开放项
1. 股市才才说是否固定 21:00？逻辑哥复盘笔记一般几点播？（决定轮询窗口；不确定就用宽窗口 13:00–22:30 兜底）
2. ASR/LLM 用哪家、API Key 由谁提供；是否允许本地跑 faster-whisper。
3. 是否需要“开播/下播提醒”；音频与逐字稿保留天数（默认 7 天）。
4. 飞书是否就用当前这个群机器人 webhook（已在 config）。
