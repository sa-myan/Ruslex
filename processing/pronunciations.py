"""Versioned, conservative headword pronunciation storage and bulk backfill.

This is deliberately independent of OCR append-only promotion. The live
migration is run only inside the network-disabled promoter container.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .openrussian import connect_reference, reference_fingerprint
from .reference_audit import audit_entries
from .storage import read_database, snapshot, write_database

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS pronunciation_schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO pronunciation_schema_versions(version, applied_at)
VALUES (1, datetime('now'));
CREATE TABLE IF NOT EXISTS lexeme_pronunciations (
    id INTEGER PRIMARY KEY,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    stressed TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('openrussian', 'manual', 'other')),
    reference_id TEXT NOT NULL DEFAULT '',
    reference_fingerprint TEXT NOT NULL DEFAULT '',
    verification TEXT NOT NULL DEFAULT 'source_backed'
        CHECK (verification IN ('source_backed','verified','disputed')),
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(lexeme_id, stressed)
);
CREATE INDEX IF NOT EXISTS idx_lexeme_pronunciations_lexeme
    ON lexeme_pronunciations(lexeme_id);
CREATE TABLE IF NOT EXISTS sense_pronunciations (
    sense_id INTEGER NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
    pronunciation_id INTEGER NOT NULL REFERENCES lexeme_pronunciations(id) ON DELETE CASCADE,
    PRIMARY KEY(sense_id, pronunciation_id)
);
CREATE TRIGGER IF NOT EXISTS sense_pronunciations_match_insert
BEFORE INSERT ON sense_pronunciations
BEGIN
    SELECT CASE WHEN
       (SELECT lexeme_id FROM senses WHERE id=NEW.sense_id) IS NOT
       (SELECT lexeme_id FROM lexeme_pronunciations WHERE id=NEW.pronunciation_id)
    THEN RAISE(ABORT,'sense pronunciation belongs to a different lexeme') END;
END;
CREATE TRIGGER IF NOT EXISTS sense_pronunciations_match_update
BEFORE UPDATE ON sense_pronunciations
BEGIN
    SELECT CASE WHEN
       (SELECT lexeme_id FROM senses WHERE id=NEW.sense_id) IS NOT
       (SELECT lexeme_id FROM lexeme_pronunciations WHERE id=NEW.pronunciation_id)
    THEN RAISE(ABORT,'sense pronunciation belongs to a different lexeme') END;
END;
"""


def installed(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_pronunciations'"
    ).fetchone() is not None


def _check(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Dictionary integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Dictionary foreign keys are invalid")


def _backup(live: Path, backups: Path, purpose: str) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = backups / f"before-stress-{purpose}-{stamp}.db"
    snapshot(live, dest)
    dest.chmod(0o600)
    with read_database(dest) as db:
        _check(db)
    return dest


def initialize(live: Path, backups: Path) -> dict:
    with read_database(live) as db:
        _check(db)
        if installed(db):
            return {"installed": True, "changed": False}
    backup = _backup(live, backups, "schema")
    # executescript commits implicitly, so use explicit BEGIN/COMMIT in one script.
    with write_database(live) as db:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        _check(db)
    return {"installed": True, "changed": True, "backup": str(backup),
            "schema_version": SCHEMA_VERSION}


def backfill_plan(live: Path, reference: Path) -> dict:
    with read_database(live) as lexicon, connect_reference(reference) as ref:
        _check(lexicon)
        rows = audit_entries(ref, lexicon)
        has_storage = installed(lexicon)
        present = set()
        if has_storage:
            present = {r[0] for r in lexicon.execute(
                """SELECT DISTINCT p.lexeme_id FROM lexeme_pronunciations p
                   JOIN lexemes l ON l.id=p.lexeme_id
                   WHERE l.entry_type='word' AND l.human_status != 'hidden'"""
            )}
    candidates = [r for r in rows if r["safe_backfill"] and r["lexeme_id"] not in present]
    from collections import Counter
    return {
        "schema_installed": has_storage,
        "total_headwords": len(rows),
        "hidden_entries_excluded": True,
        "statuses": dict(Counter(r["status"] for r in rows)),
        "backfill_methods": dict(Counter(r["backfill_method"] for r in candidates)),
        "backfill_blockers": dict(Counter(r["backfill_blocker"] for r in rows if r["lexeme_id"] not in present and not r["safe_backfill"])),
        "candidate_blocked_reference_types": dict(Counter(r["reference_types"] for r in rows if r["lexeme_id"] not in present and r["status"] == "candidate" and not r["safe_backfill"]).most_common(12)),
        "yo_checks": dict(Counter(r["yo_check"] for r in rows)),
        "safe_new_pronunciations": len(candidates),
        "existing_pronunciations_skipped": len(present),
        "unresolved": len(rows) - len(candidates) - sum(r["lexeme_id"] in present for r in rows),
        "reference_sha256": reference_fingerprint(reference),
        "preview": [{"id": r["lexeme_id"], "lemma": r["lemma"],
                     "stressed": r["stress_candidates"]} for r in candidates[:20]],
        "data_mutation": "none",
    }


def apply_backfill(live: Path, reference: Path, backups: Path) -> dict:
    preview = backfill_plan(live, reference)
    if not preview["schema_installed"]:
        raise RuntimeError("Run stress init --confirm before backfill")
    if not preview["safe_new_pronunciations"]:
        return {**preview, "inserted": 0}
    backup = _backup(live, backups, "backfill")
    # Compute candidates once more inside the write transaction: readings and
    # current lexemes are selected together. Existing pronunciations win.
    with connect_reference(reference) as ref, write_database(live) as db:
        db.execute("BEGIN IMMEDIATE")
        rows = audit_entries(ref, db)
        fingerprint = reference_fingerprint(reference)
        stamp = datetime.now(timezone.utc).isoformat()
        count = 0
        for row in rows:
            if not row["safe_backfill"]:
                continue
            if db.execute(
                "SELECT 1 FROM lexeme_pronunciations WHERE lexeme_id=?",
                (row["lexeme_id"],)
            ).fetchone():
                continue
            # A single stressed spelling may have multiple OpenRussian IDs.
            reference_id = row["reference_ids"].split(",")[0]
            db.execute(
                """INSERT INTO lexeme_pronunciations
                   (lexeme_id, stressed, source, reference_id,
                    reference_fingerprint, verification, is_primary, created_at)
                   VALUES (?, ?, 'openrussian', ?, ?, 'source_backed', 1, ?)""",
                (row["lexeme_id"], row["stress_candidates"], reference_id,
                 fingerprint, stamp),
            )
            count += 1
        _check(db)
    return {**preview, "inserted": count, "backup": str(backup),
            "data_mutation": "pronunciations_inserted" if count else "none"}


def backfill_new_lexemes(db: sqlite3.Connection, reference: Path,
                         lexeme_ids: set[int]) -> int:
    """Populate safe readings for newly promoted words in the same transaction.

    If the optional reference is absent, book promotion remains usable.
    A present but malformed reference must fail loudly, never guess.
    """
    if not lexeme_ids or not installed(db) or not reference.is_file():
        return 0
    with connect_reference(reference) as ref:
        rows = audit_entries(ref, db)
        fingerprint = reference_fingerprint(reference)
    stamp = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for row in rows:
        if row["lexeme_id"] not in lexeme_ids or not row["safe_backfill"]:
            continue
        if db.execute(
            "SELECT 1 FROM lexeme_pronunciations WHERE lexeme_id=?",
            (row["lexeme_id"],)
        ).fetchone():
            continue
        db.execute(
            """INSERT INTO lexeme_pronunciations
               (lexeme_id, stressed, source, reference_id, reference_fingerprint,
                verification, is_primary, created_at)
               VALUES (?, ?, 'openrussian', ?, ?, 'source_backed', 1, ?)""",
            (row["lexeme_id"], row["stress_candidates"],
             row["reference_ids"].split(",")[0], fingerprint, stamp),
        )
        inserted += 1
    return inserted


def rehearse(live: Path, reference: Path, workspace_root: Path) -> dict:
    """Test schema and backfill on a fresh consistent copy; never write live.

    Runs as the ordinary unprivileged worker, where /live and /reference are
    read-only. No network, user credentials, or production mutation needed.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    root = workspace_root / "stress_rehearsals" / stamp
    root.mkdir(parents=True, exist_ok=False)
    copy = root / "lexicon.db"
    snapshot(live, copy)
    with read_database(live) as db:
        original_counts = {
            table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("lexemes", "senses", "lexeme_relations", "lexeme_pages")
        }
    before = backfill_plan(copy, reference)
    migration = initialize(copy, root / "backups")
    after_install = backfill_plan(copy, reference)
    first = apply_backfill(copy, reference, root / "backups")
    second = apply_backfill(copy, reference, root / "backups")
    with read_database(copy) as db:
        _check(db)
        after_counts = {
            table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in original_counts
        }
        total_readings = db.execute(
            "SELECT COUNT(*) FROM lexeme_pronunciations"
        ).fetchone()[0]
    if after_counts != original_counts or second["inserted"]:
        raise RuntimeError("Rehearsal failed: existing data changed or backfill was not idempotent")
    if before["safe_new_pronunciations"] != first["inserted"]:
        raise RuntimeError("Rehearsal failed: backfill differs from read-only plan")
    return {
        "success": True,
        "production_modified": False,
        "rehearsal_path": str(root),
        "before": before,
        "schema": migration,
        "after_install": after_install,
        "inserted": first["inserted"],
        "second_pass_inserted": second["inserted"],
        "total_pronunciations": total_readings,
        "existing_data_counts_unchanged": True,
    }
