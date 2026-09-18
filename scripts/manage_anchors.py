"""Manage configured anchors without exposing or rewriting unrelated settings."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "anchors.json"


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    add.add_argument("--uid", required=True)
    bili = sub.add_parser("add-bilibili")
    bili.add_argument("--mid", required=True)
    bili.add_argument("--room-id", required=True)
    bili.add_argument("--name", required=True)
    delete = sub.add_parser("delete")
    delete.add_argument("--id", required=True)
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    anchors = config.setdefault("anchors", [])
    if args.action == "delete":
        config["anchors"] = [item for item in anchors if item.get("id") != args.id]
        if len(config["anchors"]) == len(anchors):
            raise SystemExit("未找到该主播 ID")
    elif args.action == "add":
        if any(item.get("id") == args.uid for item in anchors):
            raise SystemExit("该 ID 已存在")
        item = {"id": args.uid, "uid": args.uid, "platform": "douyin",
                "name": args.uid, "poll_windows": [["00:00", "23:59"]]}
        anchors.append(item)
    else:
        anchor_id = "bili_" + args.mid
        if any(item.get("id") == anchor_id for item in anchors):
            raise SystemExit("该 B 站主播已存在")
        anchors.append({"id": anchor_id, "platform": "bilibili", "name": args.name,
                        "mid": args.mid, "room_id": args.room_id,
                        "poll_windows": [["00:00", "23:59"]]})
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("主播已添加" if args.action == "add" else "主播已删除")


if __name__ == "__main__":
    main()
