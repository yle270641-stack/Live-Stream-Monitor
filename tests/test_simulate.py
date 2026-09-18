import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulationTests(unittest.TestCase):
    def run_simulation(self, output_dir, keep=False):
        env = os.environ.copy()
        env.pop("LLM_API_KEY", None)
        args = [sys.executable, str(ROOT / "scripts" / "simulate.py"),
                "--output-dir", str(output_dir)]
        if keep:
            args.append("--keep-transcript")
        return subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                              text=True, encoding="utf-8", check=True)

    def test_offline_simulation_is_isolated_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = json.loads(self.run_simulation(tmp).stdout.split("\n\n", 1)[0])
            second = json.loads(self.run_simulation(tmp).stdout.split("\n\n", 1)[0])
            self.assertEqual(first["mode"], "offline")
            self.assertNotEqual(first["summary_path"], second["summary_path"])
            files = list(Path(tmp).glob("*.summary.txt"))
            self.assertEqual(len(files), 2)
            self.assertTrue(all("不构成投资建议" in p.read_text(encoding="utf-8") for p in files))

    def test_keep_transcript_keeps_fixture_next_to_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_simulation(tmp, keep=True)
            self.assertEqual(len(list(Path(tmp).glob("*.txt"))), 2)
