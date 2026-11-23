#!/usr/bin/env python3
"""Safe online SQLite backups for BOTH databases (no raw live file copying)."""
from datetime import datetime, timezone
from pathlib import Path
import os, sqlite3


def backup(source:Path,destination:Path):
    if not source.is_file():raise FileNotFoundError(source)
    if destination.exists():raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro",uri=True) as db:
        with sqlite3.connect(destination) as target:db.backup(target)
    with sqlite3.connect(destination) as check:
        assert check.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    destination.chmod(0o600)
    print("Backed up:",destination)

if __name__=="__main__":
    root=Path(os.getenv("DATA_ROOT","/srv/data/ruslex"))
    # Don't source an untrusted .env as a shell script.
    env=Path(__file__).resolve().parents[1]/".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("DATA_ROOT="):root=Path(line.split('=',1)[1]);break
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    directory=root/"backups"/stamp
    backup(root/"lexicon"/"lexicon.db",directory/"lexicon.db")
    admin=root/"admin"/"admin.sqlite3"
    if admin.exists():backup(admin,directory/"admin.sqlite3")
    print("Backup directory:",directory)
