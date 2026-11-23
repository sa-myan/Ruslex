#!/usr/bin/env python3
"""Consistent online SQLite backups for both independent Ruslex databases."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def data_root() -> Path:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.is_file():
        raise FileNotFoundError("Missing .env; run ./manage.sh init")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA_ROOT="):
            return Path(line.split("=", 1)[1].strip()).resolve()
    raise ValueError("DATA_ROOT is missing in .env")


def backup(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy)
    with closing(sqlite3.connect(target)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Backup failed integrity check: {target}")
        if check.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(f"Backup has foreign-key violations: {target}")
    target.chmod(0o600)


def backup_both(root: Path, *, prefix: str = "") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory = root / "backups" / (prefix + stamp)
    directory.mkdir(parents=True, exist_ok=False)
    backup(root / "lexicon" / "lexicon.db", directory / "lexicon.db")
    admin = root / "admin" / "admin.sqlite3"
    if admin.is_file():
        backup(admin, directory / "admin.sqlite3")
    print("Database backup directory:", directory)
    return directory


if __name__ == "__main__":
    backup_both(data_root())
