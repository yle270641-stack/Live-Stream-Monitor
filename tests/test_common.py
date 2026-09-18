import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common


def valid_config(webhook=""):
    return {
        "anchors": [{
            "id": "bili_example",
            "name": "示例主播",
            "platform": "bilibili",
            "mid": "123",
            "room_id": "456",
            "poll_windows": [["23:00", "01:00"]],
        }],
        "feishu_webhook": webhook,
        "retention_days": 7,
    }


class ConfigTests(unittest.TestCase):
    def test_env_webhook_overrides_file_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anchors.json"
            path.write_text(json.dumps(valid_config("https://from-file.example")), encoding="utf-8")
            with patch.object(common, "CONFIG_PATH", path), patch.dict(
                os.environ, {"FEISHU_WEBHOOK": "https://from-env.example"}
            ):
                self.assertEqual(common.load_config()["feishu_webhook"], "https://from-env.example")

    def test_missing_config_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "anchors.json"
            with patch.object(common, "CONFIG_PATH", missing):
                with self.assertRaisesRegex(FileNotFoundError, "anchors.example.json"):
                    common.load_config()

    def test_duplicate_anchor_ids_are_rejected(self):
        config = valid_config()
        config["anchors"].append(dict(config["anchors"][0]))
        errors, _ = common.inspect_config(config)
        self.assertTrue(any("重复" in item for item in errors))

    def test_placeholder_is_rejected_for_real_config(self):
        config = valid_config()
        config["anchors"][0]["room_id"] = "替换为直播间 room_id"
        errors, _ = common.inspect_config(config)
        self.assertTrue(any("占位符" in item for item in errors))

    def test_non_object_root_is_rejected(self):
        errors, _ = common.inspect_config([])
        self.assertIn("配置根节点必须是 JSON 对象", errors)

    def test_invalid_webhook_and_time_are_rejected(self):
        config = valid_config("http://insecure.example")
        config["anchors"][0]["poll_windows"] = [["25:00", "26:00"]]
        errors, _ = common.inspect_config(config)
        self.assertTrue(any("HTTPS" in item for item in errors))
        self.assertTrue(any("HH:MM" in item for item in errors))


class TimeWindowTests(unittest.TestCase):
    def test_regular_window(self):
        self.assertTrue(common.time_in_windows("12:00", [["09:00", "13:00"]]))
        self.assertFalse(common.time_in_windows("14:00", [["09:00", "13:00"]]))

    def test_cross_midnight_window(self):
        windows = [["23:00", "01:00"]]
        self.assertTrue(common.time_in_windows("23:30", windows))
        self.assertTrue(common.time_in_windows("00:30", windows))
        self.assertFalse(common.time_in_windows("12:00", windows))


if __name__ == "__main__":
    unittest.main()
