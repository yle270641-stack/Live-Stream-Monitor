# 财经直播助手 · 运行手册（定时任务到点照此执行）

> 目标：监听 2 个抖音 + 1 个 B站财经直播间，开播后**只录音频**，转写并提炼五段式纪要，经飞书机器人推送。
> 全部命令在 **PowerShell** 中、于 `scripts` 目录下用 `python` 运行。仅用标准库，勿擅自 pip 安装。

## 0. 路径与配置
- 项目根：`C:\Users\Yule2\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\finance-live-watcher`
- 主播与工具配置：`config/anchors.json`（含三个 anchor 的 id/sec_uid/room_id、webhook）
- 目录：`recordings/`（音频）、`transcripts/`（逐字稿）、`logs/`（日志与流地址）
- 主播 id：`douyin_caicaishuo`（股市才才说）、`douyin_wending`（文鼎）、`bili_luojige`（逻辑哥复盘笔记）

## 1. B站：全自动，无需浏览器
```powershell
cd "<项目根>\scripts"
python bili_live.py status --anchor bili_luojige     # 看 is_live
# 若 is_live=true：
python bili_live.py playurl --anchor bili_luojige    # 取 chosen.url
python record_audio.py --url "<chosen.url>" --referer "https://live.bilibili.com/1785947366" --out "recordings/bili_<MMDDHHMM>.mp3" --seconds 120
```
- 试录 `--seconds 120`；正式整场录制用 `--seconds 0`（录到下播自然结束）。

## 2. 抖音：必须用受控浏览器（computer_use_tool, plane="bu"）取流
登录态保存在受控浏览器 profile 中，**不要读取/导出 cookie**。流程：
```python
import seed_browser_use as bu, time
# sec_uid 从 config/anchors.json 取
bu.navigate("https://www.douyin.com/user/<sec_uid>"); bu.wait_for_load(timeout=20); time.sleep(2)
# ① 判断是否开播：开播时主页出现“直播中”入口，链接形如 https://live.douyin.com/<web_rid>
#    用 snapshot/get_page_text/network_requests 找到该 web_rid；未开播则本轮跳过
bu.navigate("https://live.douyin.com/<web_rid>"); bu.wait_for_load(timeout=20); time.sleep(4)
reqs = bu.network_requests()
flv=[]
for r in reqs:
    u=r.get("url") if isinstance(r,dict) else str(r)
    if isinstance(u,str) and "douyincdn.com" in u and ".flv?" in u and u not in flv: flv.append(u)
assert flv, "未抓到流，可 reload 后等 5s 再抓一次，最多 2 次"
open(r"<项目根>\logs\_stream_<anchor>.txt","w",encoding="utf-8").write(flv[0])
print(flv[0])
```
回到 PowerShell 录音（URL 从 logs 文件读，避免特殊字符问题）：
```powershell
$u=(Get-Content "<项目根>\logs\_stream_<anchor>.txt" -Raw).Trim()
python record_audio.py --url "$u" --referer "https://live.douyin.com/" --out "recordings/<anchor>_<MMDDHHMM>.mp3" --seconds 120
```

## 3. 转写（音频 → 逐字稿）
```powershell
python transcribe.py --audio "recordings/<file>.mp3"
# 返回 JSON：ok/minute_url/transcript_path/chars/text；text 即逐字稿
```

## 4. 提炼五段式纪要（读取逐字稿后由你生成，客观转述）
结构固定：
- 头部：主播名 · 直播起止时间 · 时长 ·（试录/正式）
- ① 一句话核心观点 ② 大盘/仓位判断 ③ 看好与看空板块 ④ 提到的个股与操作（**带逐字稿时间点**）⑤ 风险提示
- 尾部固定：`仅作客观转述，不构成投资建议。逐字稿：<minute_url>`
- 只依据逐字稿，不得补充逐字稿中没有的观点、数字或个股。

## 5. 推送（webhook 已配置）
```powershell
# 正文写入 notes.txt 后：
python feishu_push.py --title "<主播名> · 直播纪要（<时间>）" --body-file "<notes.txt 相对项目根路径>"
```

## 6. 异常处理（必须遵守，禁止静默失败）
- 浏览器出现登录二维码 / `blocked=auth`：立即 `interaction.request_action(type="browserControl")` 请用户扫码，完成后重新 snapshot，不得绕过、不得改用未登录通道。
- 抓不到流：reload 直播间、等待后重抓，最多 2 次；仍失败则推送「<主播> 取流失败：<原因>」，并尝试回放/切片兜底。
- 未开播：本轮跳过并记录，不产出空纪要。
- 转写超时：按脚本内轮询；超过上限推送「转写仍在处理，附 minute_url」。
- 任一步失败都要让用户在飞书看到原因，绝不假装成功。

## 7. 试录验收标准（阶段B）
对每个目标主播：开播后录 120 秒音频 → 转写出非空逐字稿 → 飞书推送一条带“【试录】”标记的样例纪要。三者都成即该主播通过；否则推送具体失败环节。
