"""Regression checks for safe, VPS-local processing-state setup (no Docker needed)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class ProcessingLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "process.sh").write_bytes((PROJECT / "process.sh").read_bytes())
        (self.project / "process.sh").chmod(0o755)
        self.data = self.root / "data"
        self.uid = "1234"
        (self.project / ".env").write_text(
            f"DATA_ROOT={self.data}\nPUID={self.uid}\nPGID=1234\n"
        )
        binary = self.root / "bin"
        binary.mkdir()
        fake_docker = binary / "docker"
        fake_docker.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$MOCK_DOCKER_LOG"\n'
            'case " $* " in\n'
            '  *" state-init "*)\n'
            '    mkdir -p "$MOCK_DATA_ROOT/processing/state"\n'
            '    touch "$MOCK_DATA_ROOT/processing/state/.ruslex-ready-$MOCK_UID"\n'
            '    ;;\n'
            'esac\n'
        )
        fake_docker.chmod(0o755)
        self.log = self.root / "docker.log"
        self.env = os.environ.copy()
        self.env.update(
            PATH=f"{binary}:{os.environ.get('PATH', '')}",
            MOCK_DOCKER_LOG=str(self.log),
            MOCK_DATA_ROOT=str(self.data),
            MOCK_UID=self.uid,
        )

    def run_command(self, *args):
        return subprocess.run(
            ["sh", "./process.sh", *args],
            cwd=self.project,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_first_use_prepares_state_only_once(self):
        self.assertEqual(self.run_command("version").returncode, 0)
        self.assertEqual(len(self.log_lines()), 2)
        self.assertIn("state-init", self.log_lines()[0])
        self.assertIn("opencode worker --version", self.log_lines()[1])

        self.assertEqual(self.run_command("version").returncode, 0)
        self.assertEqual(len(self.log_lines()), 3)
        self.assertNotIn("state-init", self.log_lines()[2])

    def test_repair_is_explicit_and_safe_to_repeat(self):
        result = self.run_command("repair-state")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.log_lines()), 1)
        self.assertIn("state-init", self.log_lines()[0])

    def test_stress_read_only_approval_plan_reaches_rehearsal(self):
        result = self.run_command(
            "stress", "ai-approval-plan", "stress43_trial2", "--approve", "21,93"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log_lines(), [
            "compose -f docker-compose.processing.yml run --rm --no-deps "
            "rehearsal python -m processing.cli stress ai-approval-plan "
            "stress43_trial2 --approve 21,93"
        ])

    def test_stress_apply_uses_promoter_not_worker(self):
        result = self.run_command(
            "stress", "ai-apply", "stress43_trial2", "--confirm", "--approve", "21,93"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log_lines(), [
            "compose -f docker-compose.processing.yml run --rm --no-deps "
            "promoter python -m processing.cli stress ai-apply "
            "stress43_trial2 --confirm --approve 21,93"
        ])

    def test_bad_uid_does_not_launch_docker(self):
        (self.project / ".env").write_text(
            f"DATA_ROOT={self.data}\nPUID=0\nPGID=1234\n"
        )
        result = self.run_command("version")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not run as root", result.stderr)
        self.assertEqual(self.log_lines(), [])

    def test_bad_data_root_does_not_launch_docker(self):
        (self.project / ".env").write_text(
            "DATA_ROOT=relative/path\nPUID=1234\nPGID=1234\n"
        )
        result = self.run_command("version")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absolute path", result.stderr)
        self.assertEqual(self.log_lines(), [])


if __name__ == "__main__":
    unittest.main()
