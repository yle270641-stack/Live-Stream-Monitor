import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common


class ConfigTests(unittest.TestCase):
    def test_env_webhook_overrides_file_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anchors.json"
            path.write_text(
                json.dumps({"anchors": [], "feishu_webhook": "from-file"}),
                encoding="utf-8",
            )
            with patch.object(common, "CONFIG_PATH", path), patch.dict(
                os.environ, {"FEISHU_WEBHOOK": "from-env"}
            ):
                self.assertEqual(common.load_config()["feishu_webhook"], "from-env")

    def test_missing_config_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "anchors.json"
            with patch.object(common, "CONFIG_PATH", missing):
                with self.assertRaisesRegex(FileNotFoundError, "anchors.example.json"):
                    common.load_config()


if __name__ == "__main__":
    unittest.main()
