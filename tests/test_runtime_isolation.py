"""Runtime isolation contracts: no Docker daemon or production data required."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class RuntimeIsolationTests(unittest.TestCase):
    def test_public_container_mounts_only_required_databases(self):
        compose = (PROJECT / "docker-compose.yml").read_text(encoding="utf-8")
        web = compose.split("services:\n", 1)[1].split("\nnetworks:\n", 1)[0]
        mount_section = web.split("    volumes:\n", 1)[1].split("\n    networks:", 1)[0]
        mounts = re.findall(r'^\s+- "([^"]+)"\s*$', mount_section, re.MULTILINE)
        self.assertEqual(mounts, [
            "${DATA_ROOT}/lexicon:/data/lexicon",
            "${DATA_ROOT}/admin:/data/admin",
        ])
        self.assertNotIn("${DATA_ROOT}:/data", compose)

    def test_smoke_launcher_never_mounts_private_data_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(PROJECT / "manage.sh", root / "manage.sh")
            (root / ".env").write_text(
                "DATA_ROOT=/srv/test-only-ruslex\nPUID=1234\nPGID=1234\n",
                encoding="utf-8",
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_DOCKER_ARGS"\n',
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            log = root / "args.txt"
            env = dict(os.environ, TEST_DOCKER_ARGS=str(log))
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                ["sh", "./manage.sh", "test"], cwd=root, env=env,
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = log.read_text(encoding="utf-8").splitlines()
            for required in ("run", "--rm", "--network", "none", "--read-only",
                             "/srv/test-only-ruslex/lexicon:/data/lexicon:ro",
                             "ruslex:local", "/app/scripts/smoke_test.py"):
                self.assertIn(required, args)
            self.assertNotIn("--env-file", args)
            self.assertFalse(any("/processing" in a or "/reference" in a
                                 or "/admin" in a or "/ocr" in a or "/backups" in a
                                 for a in args if a.startswith("/srv/")))

    def test_book_rehearsal_smoke_mounts_only_disposable_snapshot(self):
        script = (PROJECT / "scripts/verify_book_pipeline.sh").read_text(encoding="utf-8")
        self.assertIn('-v "$db_path:/data/lexicon/lexicon.db:ro"', script)
        self.assertIn("--network none --read-only", script)
        self.assertNotIn('-v "$data_root:/data:ro"', script)

    def test_smoke_launcher_rejects_invalid_root_before_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(PROJECT / "manage.sh", root / "manage.sh")
            (root / ".env").write_text(
                "DATA_ROOT=relative\nPUID=1234\nPGID=1234\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["sh", "./manage.sh", "test"], cwd=root,
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("absolute path", result.stderr)


if __name__ == "__main__":
    unittest.main()
