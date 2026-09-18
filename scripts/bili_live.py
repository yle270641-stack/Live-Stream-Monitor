# -*- coding: utf-8 -*-
"""B站直播：查询开播状态 / 解析直播流地址。无需登录，仅标准库。
用法：
  python bili_live.py status --anchor bili_luojige
  python bili_live.py playurl --anchor bili_luojige
"""
import argparse
import json
import time
import urllib.request

from common import load_config, get_anchor, out_json, UA


def http_get(url, referer, retries=3):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "application/json",
    })
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s 退避
    raise last_exc


def status(cfg, anchor):
    room = anchor["room_id"]
    mid = anchor.get("mid", room)
    # getRoomInfoOld 以用户 mid 查询；误传 room_id 会返回 -400
    url = f"https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid={mid}"
    j = http_get(url, f"https://live.bilibili.com/{room}")
    d = j.get("data", {})
    ls = d.get("live_status")
    if ls is None:
        ls = d.get("liveStatus")  # getRoomInfoOld 返回的是驼峰命名
    return {
        "platform": "bilibili",
        "id": anchor["id"],
        "name": d.get("uname") or anchor["name"],
        "room_id": room,
        "live_status": ls,  # 0未播 1开播 2轮播
        "is_live": ls == 1,
        "title": d.get("title", ""),
        "live_url": f"https://live.bilibili.com/{room}",
        "raw_code": j.get("code"),
    }


def playurl(cfg, anchor):
    room = anchor["room_id"]
    url = (f"https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo?"
           f"room_id={room}&protocol=0,1&format=0,1,2&codec=0,1&qn=10000&platform=web")
    j = http_get(url, f"https://live.bilibili.com/{room}")
    data = j.get("data", {})
    picks = []
    pli = (data.get("playurl_info") or {}).get("playurl", {})
    for stream in pli.get("stream", []):
        for fmt in stream.get("format", []):
            for codec in fmt.get("codec", []):
                base = codec.get("base_url", "")
                for ui in codec.get("url_info", []):
                    picks.append({
                        "protocol": stream.get("protocol_name"),
                        "format": fmt.get("format_name"),
                        "codec": codec.get("codec_name"),
                        "qn": codec.get("current_qn"),
                        "url": ui.get("host", "") + base + ui.get("extra", ""),
                    })
    # 优先 http_stream + flv + avc，最通用
    def score(x):
        return (x["format"] == "flv", x["protocol"] == "http_stream", x["codec"] == "avc")
    picks.sort(key=score, reverse=True)
    chosen = picks[0] if picks else None
    return {
        "id": anchor["id"],
        "live_status": data.get("live_status"),
        "is_live": data.get("live_status") == 1,
        "chosen": chosen,
        "all": picks,
    }


def main():
    import io as _io
    import sys as _sys
    if hasattr(_sys.stdout, "buffer"):
        _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(_sys.stderr, "buffer"):
        _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "playurl"])
    ap.add_argument("--anchor", required=True)
    args = ap.parse_args()
    cfg = load_config()
    anchor = get_anchor(cfg, args.anchor)
    if args.cmd == "status":
        out_json(status(cfg, anchor))
    else:
        out_json(playurl(cfg, anchor))


if __name__ == "__main__":
    main()
