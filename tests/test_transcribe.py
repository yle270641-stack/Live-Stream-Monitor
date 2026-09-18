import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from transcribe import detect_device


class DeviceDetectionTests(unittest.TestCase):
    def test_explicit_cpu_wins(self):
        with patch.dict(os.environ, {"WHISPER_DEVICE": "cpu", "WHISPER_COMPUTE_TYPE": ""}, clear=False):
            self.assertEqual(detect_device()[:2], ("cpu", "int8"))

    def test_explicit_cuda_wins(self):
        with patch.dict(os.environ, {"WHISPER_DEVICE": "cuda", "WHISPER_COMPUTE_TYPE": ""}, clear=False):
            self.assertEqual(detect_device()[:2], ("cuda", "float16"))

    def test_auto_uses_cuda_when_runtime_reports_device(self):
        fake = type("FakeCTranslate2", (), {"get_cuda_device_count": staticmethod(lambda: 1)})
        with patch.dict(os.environ, {"WHISPER_DEVICE": "auto", "WHISPER_COMPUTE_TYPE": ""}, clear=False), \
             patch.dict(sys.modules, {"ctranslate2": fake}):
            self.assertEqual(detect_device()[:2], ("cuda", "float16"))


if __name__ == "__main__":
    unittest.main()
