import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from summarize import compact_transcript, fallback


class SummarizeTests(unittest.TestCase):
    def test_compact_transcript_removes_filler_and_keeps_timestamps(self):
        text = "[00:00:01] 嗯啊\n[00:00:05] 今天大盘震荡\n[00:00:40] 注意控制风险\n"
        result = compact_transcript(text)
        self.assertNotIn("嗯啊", result)
        self.assertIn("[00:00:05]", result)
        self.assertIn("[00:00:40]", result)

    def test_compact_transcript_preserves_unknown_format(self):
        text = "没有时间戳的原始内容"
        self.assertEqual(compact_transcript(text), text)

    def test_fallback_contains_disclaimer(self):
        self.assertIn("不构成投资建议", fallback("测试逐字稿"))


if __name__ == "__main__":
    unittest.main()
