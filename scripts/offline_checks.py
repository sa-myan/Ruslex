#!/usr/bin/env python3
"""Run the tests available without Django, npm or Docker installed."""

from pathlib import Path
import compileall
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for part in ("backend", "processing", "scripts", "tests"):
        if not compileall.compile_dir(ROOT / part, quiet=1):
            raise RuntimeError(f"Python syntax check failed: {part}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_*.py", "-v"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    print("OFFLINE CHECKS PASSED — live Django/Svelte execution not covered")


if __name__ == "__main__":
    main()
