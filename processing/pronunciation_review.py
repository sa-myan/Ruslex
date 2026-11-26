"""A separate, reversible pronunciation-review queue, independent of lexeme status.

This schema is installed only by the deliberate offline processing command.
It does not edit lexemes, meanings or existing pronunciation records.
"""
from __future__ import annotations

from pathlib import Path
import json

from .openrussian import connect_reference, reference_fingerprint, word_rows
from .reference_audit import audit_entries
from .stress_diagnostics import _english_glosses, _reading_options

from .pronunciations import _backup, _check
from .storage import read_database, write_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS pronunciation_review_queue(
    lexeme_id INTEGER PRIMARY KEY REFERENCES lexemes(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    deferred_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pronunciation_review_candidates(
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    reading TEXT NOT NULL,
    reference_ids TEXT NOT NULL,
    reference_types TEXT NOT NULL,
    reference_glosses TEXT NOT NULL,
    source_warnings TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY(lexeme_id,reading)
);
CREATE INDEX IF NOT EXISTS idx_pronunciation_candidates_lexeme
    ON pronunciation_review_candidates(lexeme_id);
"""


def installed(db) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pronunciation_review_queue'"
    ).fetchone() is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pronunciation_review_candidates'"
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
                     SELECT 1 FROM lexeme_pronunciations p
                     WHERE p.lexeme_id=l.id AND p.verification='verified'
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


def _candidates(db, source) -> list[tuple]:
    """Stage source options by lexeme ID and exact reading; never choose one."""
    audits = [item for item in audit_entries(source, db) if item["reference_ids"]]
    ids = list(dict.fromkeys(
        source_id for item in audits
        for source_id in item["reference_ids"].split(",") if source_id
    ))
    wanted_ids = set(ids)
    refs = {item.word_id: item for item in word_rows(source) if item.word_id in wanted_ids}
    glosses = _english_glosses(source, ids)
    result = []
    for item in audits:
        for option in _reading_options(item, refs, glosses):
            result.append((
                item["lexeme_id"], option["reading"],
                json.dumps(option["reference_ids"], ensure_ascii=False),
                json.dumps(option["reference_types"], ensure_ascii=False),
                json.dumps(option["reference_glosses"], ensure_ascii=False),
                json.dumps(option["source_warnings"], ensure_ascii=False),
            ))
    return result


def candidates_plan(live: Path, reference: Path) -> dict:
    with read_database(live) as db, connect_reference(reference) as ref:
        _check(db)
        rows = _candidates(db, ref)
        ready = installed(db)
        stored = db.execute("SELECT COUNT(*) FROM pronunciation_review_candidates").fetchone()[0] if ready else 0
    return {
        "schema_ready": ready,
        "candidate_rows": len(rows),
        "entries_with_options": len({row[0] for row in rows}),
        "existing_cached_rows": stored,
        "sample": [{"lexeme_id": row[0], "reading": row[1]} for row in rows[:12]],
        "reference_sha256": reference_fingerprint(reference),
        "data_mutation": "none",
    }


def refresh_candidates(live: Path, reference: Path, backups: Path) -> dict:
    """Populate optional editor-only suggestions; no pronunciation is saved."""
    prior = candidates_plan(live, reference)
    if not prior["schema_ready"]:
        raise RuntimeError("Run pronunciation-review init --confirm first")
    backup = _backup(live, backups, "pronunciation-review-candidates")
    fingerprint = prior["reference_sha256"]
    with connect_reference(reference) as ref, write_database(live) as db:
        db.execute("BEGIN IMMEDIATE")
        options = _candidates(db, ref)
        if reference_fingerprint(reference) != fingerprint:
            raise RuntimeError("OpenRussian reference changed; aborting")
        if len(options) != prior["candidate_rows"]:
            raise RuntimeError("Candidate count changed; aborting")
        db.execute("DELETE FROM pronunciation_review_candidates")
        db.executemany(
            """INSERT INTO pronunciation_review_candidates
               (lexeme_id,reading,reference_ids,reference_types,reference_glosses,source_warnings,fingerprint)
               VALUES (?,?,?,?,?,?,?)""",
            [(*row, fingerprint) for row in options],
        )
        _check(db)
    return {
        "cached_options": len(options), "entries_with_options": len({row[0] for row in options}),
        "reference_sha256": fingerprint, "backup": str(backup),
        "data_mutation": "candidate_cache_replaced",
    }
