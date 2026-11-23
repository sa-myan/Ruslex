#!/usr/bin/env python3
"""One-time VPS initialization; never builds images or changes the shared proxy.

Examples:
  python3 scripts/install.py --dry-run
  python3 scripts/install.py --source-db /path/to/existing/lexicon.db
  python3 scripts/install.py  # existing /srv/data/ruslex/lexicon/lexicon.db
"""
from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"Invalid SQLite database: {path}")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError(f"Foreign-key errors: {path}")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"lexemes", "senses", "pages", "reviews"} <= tables:
            raise ValueError("Source is not an initialized Ruslex dictionary")


def initialize(*, root: Path, source: Path | None, hostname: str, dry_run: bool) -> dict:
    root = root.resolve()
    if root == ROOT or root.is_relative_to(ROOT):
        raise ValueError("Persistent data must be outside the Git checkout")
    lexicon = root / "lexicon" / "lexicon.db"
    admin = root / "admin" / "admin.sqlite3"
    environment = ROOT / ".env"
    if lexicon.exists():
        validate_database(lexicon)
    elif source:
        validate_database(source)
    else:
        raise ValueError("First installation requires --source-db /path/to/existing/lexicon.db")
    if lexicon.resolve() == admin.resolve():
        raise ValueError("Dictionary and Django administrator databases must be separate")
    result = {"data_root": str(root), "lexicon": str(lexicon),
              "existing_dictionary": lexicon.exists(),
              "existing_environment": environment.exists(), "dry_run": dry_run}
    if dry_run:
        return result
    for folder in (root, root / "lexicon", root / "admin", root / "backups",
                   root / "processing", root / "processing" / "state", root / "ocr", root / "releases"):
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o750)
    if not lexicon.exists():
        with closing(sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(lexicon)) as destination:
                original.backup(destination)
        validate_database(lexicon)
        lexicon.chmod(0o640)
    if not environment.exists():
        if not hostname or "." not in hostname or any(c.isspace() for c in hostname):
            raise ValueError("Provide a valid --hostname for first-time initialization")
        config = (
            f"DJANGO_SECRET_KEY={secrets.token_urlsafe(48)}\n"
            f"DJANGO_ALLOWED_HOSTS={hostname},127.0.0.1,localhost\n"
            f"PUBLIC_ORIGIN=https://{hostname}\n"
            "HTTPS_ENABLED=1\n"
            f"DATA_ROOT={root}\nPUID={os.getuid()}\nPGID={os.getgid()}\n"
        )
        # Exclusive creation: never replace an existing secret or environment file.
        with environment.open("x", encoding="utf-8") as handle:
            handle.write(config)
        environment.chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("/srv/data/ruslex"))
    parser.add_argument("--hostname", default="ruslex.2-29-159-213.sslip.io")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import json
    print(json.dumps(initialize(root=args.data_root, source=args.source_db,
                                hostname=args.hostname, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
