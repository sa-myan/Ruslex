#!/usr/bin/env python3
"""Manual, explicit restore of database backups while Ruslex web is STOPPED."""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
import subprocess
import tempfile
from pathlib import Path

from backup import backup_both, data_root

ROOT = Path(__file__).resolve().parents[1]


def web_is_running():
    check = subprocess.run(["docker", "compose", "ps", "--status", "running", "-q", "web"],
                           cwd=ROOT, capture_output=True, text=True, check=True)
    return bool(check.stdout.strip())


def restore_one(source: Path, target: Path):
    # Never overwrite an active WAL database, and never copy live SQLite bytes.
    for suffix in ("-wal", "-shm"):
        if Path(str(target) + suffix).exists():
            raise RuntimeError(f"Unresolved SQLite sidecar {target}{suffix}; inspect before restore")
    with tempfile.NamedTemporaryFile(prefix=".restore-", suffix=".db",
                                     dir=target.parent, delete=False) as file:
        temp = Path(file.name)
    try:
        with closing(sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(temp)) as destination:
                original.backup(destination)
        with closing(sqlite3.connect(temp)) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup failed integrity check")
            if check.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup failed foreign-key check")
        temp.chmod(0o640)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    root = data_root()
    lex = source / "lexicon.db"
    admin = source / "admin.sqlite3"
    if not lex.is_file() or not admin.is_file():
        raise ValueError("Restore directory must contain both lexicon.db and admin.sqlite3")
    if web_is_running():
        raise RuntimeError("Stop the website first: ./manage.sh stop")
    for target in (root / "lexicon" / "lexicon.db", root / "admin" / "admin.sqlite3"):
        for suffix in ("-wal", "-shm"):
            if Path(str(target) + suffix).exists():
                raise RuntimeError(f"Unresolved SQLite sidecar {target}{suffix}; inspect before restore")
    safety = backup_both(root, prefix="before-manual-restore-")
    print("Preserved current databases in:", safety)
    restore_one(lex, root / "lexicon" / "lexicon.db")
    restore_one(admin, root / "admin" / "admin.sqlite3")
    print("Restore completed. Run ./manage.sh start followed by ./manage.sh check")


if __name__ == "__main__":
    main()
