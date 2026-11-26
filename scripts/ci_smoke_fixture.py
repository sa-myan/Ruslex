#!/usr/bin/env python3
"""Reproduce the complete Django smoke test with no private dictionary.

Creates disposable source and test SQLite databases from the public schema;
never accesses /srv, the real lexicon, Git credentials or an AI provider.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from processing.abbreviations import initialize as init_abbreviations
from processing.paradigms import initialize as init_forms
from processing.pronunciation_review import initialize as init_review
from processing.pronunciations import initialize as init_pronunciations


def create_fixture(db_path: Path, backups: Path) -> None:
    schema = ROOT / "tests" / "fixtures" / "empty_lexicon_schema.sql"
    with sqlite3.connect(db_path) as db:
        db.executescript(schema.read_text(encoding="utf-8"))
        db.executemany(
            "INSERT INTO lexemes(id,lemma,pos,human_status) VALUES(?,?,?,?)",
            [
                (1, "читать", "VERB", "kept"),
                (2, "тайна", "NOUN", "hidden"),
                (3, "книга", "NOUN", "kept"),
            ],
        )
        db.executemany(
            "INSERT INTO senses(id,lexeme_id,meaning) VALUES(?,?,?)",
            [(1, 1, "to read"), (2, 2, "secret"), (3, 3, "book")],
        )
        db.execute("INSERT INTO tags(name,category) VALUES('vocabulary','semantic')")
        db.commit()

    # These migrations run exclusively against the synthetic database.
    init_abbreviations(db_path, backups)
    init_pronunciations(db_path, backups)
    init_forms(db_path, backups)
    init_review(db_path, backups)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """INSERT INTO lexeme_forms(
                 lexeme_id,lemma_at_generation,pos_at_generation,
                 form,form_key,grammemes,source,created_at
               ) VALUES(1,'читать','VERB','читаю','читаю',
                        'VERB,1per,pres,sing,impf','pymorphy3',datetime('now'))"""
        )
        db.commit()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ruslex-ci-") as directory:
        root = Path(directory)
        source = root / "seeded_lexicon.db"
        create_fixture(source, root / "backups")
        env = dict(os.environ)
        env.update(
            RUSLEX_SMOKE_LEXICON_SOURCE=str(source),
            PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "backend")]),
            DJANGO_SECRET_KEY="ci-only-isolated-smoke-secret",
            DJANGO_ALLOWED_HOSTS="testserver,localhost",
            HTTPS_ENABLED="0",
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test.py")],
            cwd=ROOT, env=env, check=True,
        )
    print("CI DJANGO SMOKE PASSED: all databases were temporary")


if __name__ == "__main__":
    main()
