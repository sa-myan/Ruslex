#!/usr/bin/env python3
"""Build and deploy only Ruslex; never modify shared Caddy or other apps.

Uses the current Git working tree. Default deploy requires a clean tree.
Database migrations apply only to Django's admin DB, never the lexicon DB.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call(*command: str, capture: bool = False) -> str:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, check=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def compose(*args: str, capture: bool = False) -> str:
    return call("docker", "compose", *args, capture=capture)


def commit() -> str:
    try:
        return call("git", "rev-parse", "HEAD", capture=True)
    except subprocess.CalledProcessError:
        return "unknown"


def preflight(allow_dirty=False):
    if not (ROOT / ".env").is_file():
        raise RuntimeError("Missing .env; run ./manage.sh init")
    if not allow_dirty and call("git", "status", "--porcelain", capture=True):
        raise RuntimeError("Uncommitted code changes; commit first or explicitly use --allow-dirty")
    compose("config", "--quiet")
    call("docker", "network", "inspect", "proxy", capture=True)
    from install import validate_database
    data_root = next((line.split("=", 1)[1] for line in (ROOT / ".env").read_text().splitlines()
                      if line.startswith("DATA_ROOT=")), "/srv/data/ruslex")
    validate_database(Path(data_root) / "lexicon" / "lexicon.db")
    return Path(data_root)


def healthcheck():
    endpoint = "http://127.0.0.1:8790/healthz"
    for _ in range(30):
        try:
            with urllib.request.urlopen(endpoint, timeout=3) as response:
                if response.status == 200 and response.read().strip() == b"ok":
                    return
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError(f"Ruslex did not become healthy at {endpoint}")


def migrate():
    for command in (
        ("check_lexicon",),
        ("migrate", "--database=default", "--noinput"),
        ("initialize_roles",),
        ("check",),
    ):
        compose("run", "--rm", "--no-deps", "--entrypoint", "python",
                "web", "manage.py", *command)


def build():
    compose("build", "web")


def deploy(*, allow_dirty=False):
    root = preflight(allow_dirty)
    previous_image = compose("images", "-q", "web", capture=True).splitlines()
    previous_image = previous_image[0] if previous_image else ""
    if previous_image:
        call("docker", "image", "tag", previous_image, "ruslex:previous")
    build()
    # Back up both databases before any admin migration or service replacement.
    call(sys.executable, "scripts/backup.py")
    migrate()
    try:
        compose("up", "-d", "--no-deps", "--force-recreate", "web")
        healthcheck()
    except Exception:
        print("Deployment failed; attempting to restore the previous web image", file=sys.stderr)
        if previous_image:
            call("docker", "image", "tag", previous_image, "ruslex:local")
            compose("up", "-d", "--no-deps", "--force-recreate", "web")
        # Admin DB migration rollback requires an explicit restore procedure.
        raise
    output = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "commit": commit(), "image": compose("images", "-q", "web", capture=True),
              "previous_image": previous_image}
    directory = root / "releases"
    directory.mkdir(exist_ok=True, parents=True)
    with (directory / "deployments.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(output) + "\n")
    print("Deployed Ruslex successfully; shared Caddy was not restarted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "build", "migrate", "deploy", "health"))
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    if args.command == "preflight":
        print(preflight(allow_dirty=args.allow_dirty))
    elif args.command == "build":
        preflight(allow_dirty=True)
        build()
    elif args.command == "migrate":
        preflight(allow_dirty=True)
        migrate()
    elif args.command == "deploy":
        deploy(allow_dirty=args.allow_dirty)
    else:
        healthcheck()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"ERROR: {exc}")
