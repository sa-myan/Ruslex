"""A separate, reversible pronunciation-review queue, independent of lexeme status.

This schema is installed only by the deliberate offline processing command.
It does not edit lexemes, meanings or existing pronunciation records.
"""
from __future__ import annotations

from pathlib import Path

from .pronunciations import _backup, _check
from .storage import read_database, write_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS pronunciation_review_queue(
    lexeme_id INTEGER PRIMARY KEY REFERENCES lexemes(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    deferred_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def installed(db) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pronunciation_review_queue'"
    ).fetchone() is not None


def plan(live: Path) -> dict:
    with read_database(live) as db:
        _check(db)
        has_readings = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_pronunciations'"
        ).fetchone() is not None
        if not has_readings:
            raise RuntimeError("Install pronunciation storage first")
        pending = db.execute(
            """SELECT COUNT(*) FROM lexemes l
               WHERE l.entry_type IN ('word','abbreviation')
                 AND l.human_status!='hidden'
                 AND NOT EXISTS(
                     SELECT 1 FROM lexeme_pronunciations p
                     WHERE p.lexeme_id=l.id AND p.verification='verified'
                 )"""
        ).fetchone()[0]
        ready = installed(db)
        deferred = db.execute(
            """SELECT COUNT(*) FROM pronunciation_review_queue q
               JOIN lexemes l ON l.id=q.lexeme_id
               WHERE l.entry_type IN ('word','abbreviation') AND l.human_status!='hidden'
                 AND NOT EXISTS(
                     SELECT 1 FROM lexeme_pronunciations p WHERE p.lexeme_id=l.id
                 )"""
        ).fetchone()[0] if ready else 0
    return {"schema_ready": ready, "unresolved": pending,
            "pending": pending - deferred, "deferred": deferred,
            "data_mutation": "none"}


def initialize(live: Path, backups: Path) -> dict:
    before = plan(live)
    if before["schema_ready"]:
        return {**before, "changed": False}
    backup = _backup(live, backups, "pronunciation-review-queue")
    with write_database(live) as db:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        _check(db)
    return {"schema_ready": True, "changed": True, "backup": str(backup),
            "data_mutation": "pronunciation_review_schema_added"}
