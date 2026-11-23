"""Append-only promotion of a prepared dictionary into the live SQLite database.

Never replaces a database file or any existing row. A candidate starts from a
logical SQLite backup of the live dictionary; existing records cannot be edited.
The entire live database must still match that baseline at promotion time.
A full online backup precedes each promotion, and all inserts are transactional.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .storage import atomic_json, read_database, snapshot, write_database

# Parent rows before children; SQLite FK checks remain ON during insertion.
TABLE_ORDER = (
    "books", "pages", "surface_pages", "reviews", "lexemes", "senses",
    "tags", "patterns", "examples", "sense_tags", "lexeme_pages",
    "external_links", "expression_components", "lexeme_relations", "settings",
)

# The existing app controls these settings, so AI imports cannot add them.
NO_NEW_ROWS = {"settings", "external_links"}


def _integrity(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity check failed")
    violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ValueError(f"Foreign-key violations: {violations[:3]}")


def _schema(db) -> dict:
    return {
        name: db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                         (name,)).fetchone()[0]
        for name in TABLE_ORDER
    }


def _table(db, name: str):
    fields = db.execute(f"PRAGMA table_info({name})").fetchall()
    columns = [field[1] for field in fields]
    keys = [field[1] for field in sorted(fields, key=lambda field: field[5]) if field[5]]
    if not keys:
        raise ValueError(f"Table has no primary key: {name}")
    rows = {}
    for row in db.execute(f"SELECT * FROM {name}"):
        values = tuple(row)
        identity = tuple(values[columns.index(key)] for key in keys)
        if identity in rows:
            raise ValueError(f"Duplicate primary key in {name}: {identity}")
        rows[identity] = values
    return columns, rows


def _compare(baseline, candidate):
    if _schema(baseline) != _schema(candidate):
        raise ValueError("Dictionary schema changed; use a dedicated migration, not promotion")
    changes = {}
    for name in TABLE_ORDER:
        columns, old_rows = _table(baseline, name)
        other_columns, new_rows = _table(candidate, name)
        if columns != other_columns:
            raise ValueError(f"Column mismatch in {name}")
        for identity, previous in old_rows.items():
            if identity not in new_rows:
                raise ValueError(f"Candidate deleted {name} record {identity}")
            if new_rows[identity] != previous:
                raise ValueError(f"Candidate modified existing {name} record {identity}")
        additions = {key: row for key, row in new_rows.items() if key not in old_rows}
        if additions and name in NO_NEW_ROWS:
            raise ValueError(f"Candidate cannot introduce {name} records")
        changes[name] = (columns, additions)
    return changes


def _live_matches_baseline(baseline, live):
    if _schema(baseline) != _schema(live):
        raise ValueError("Live schema differs from workspace baseline")
    for name in TABLE_ORDER:
        _, before = _table(baseline, name)
        _, now = _table(live, name)
        if before != now:
            raise RuntimeError(
                f"Live dictionary changed since workspace creation ({name}). "
                "Do not force promotion; prepare a new workspace from the current live DB."
            )


def workspace_paths(workspace: Path) -> tuple[Path, Path]:
    root = workspace.resolve()
    base, candidate, manifest = root / "baseline.db", root / "candidate.db", root / "manifest.json"
    if not base.is_file() or not candidate.is_file() or not manifest.is_file():
        raise RuntimeError("Workspace is incomplete. Run 'workspace' first")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("baseline_sha256") != hashlib.sha256(base.read_bytes()).hexdigest():
        raise RuntimeError("Workspace baseline checksum does not match manifest")
    return base, candidate


def create_workspace(live: Path, workspace: Path) -> dict:
    if workspace.exists():
        raise FileExistsError(f"Workspace already exists: {workspace}")
    workspace.mkdir(parents=True, exist_ok=False)
    baseline, candidate = workspace / "baseline.db", workspace / "candidate.db"
    try:
        snapshot(live, baseline)
        snapshot(baseline, candidate)
        with read_database(baseline) as db:
            _integrity(db)
        record = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(live),
            "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "purpose": "append-only OCR or enrichment workspace",
        }
        atomic_json(workspace / "manifest.json", record)
        return {"workspace": str(workspace), **record}
    except Exception:
        # Leave failed workspace for diagnosis rather than silently reusing it.
        raise


def plan(live: Path, workspace: Path) -> dict:
    baseline, candidate = workspace_paths(workspace)
    with read_database(baseline) as base, read_database(candidate) as proposed:
        _integrity(base)
        _integrity(proposed)
        changes = _compare(base, proposed)
        summary = {name: len(rows) for name, (_, rows) in changes.items() if rows}
        with read_database(live) as production:
            _integrity(production)
            _live_matches_baseline(base, production)
    reviews = changes["reviews"][1].values()
    statuses = {"pending": 0, "needs_review": 0}
    for record in reviews:
        # SQLite reviews schema: id,book_id,surface,analyses_json,status,...
        status = record[4]
        if status in statuses:
            statuses[status] += 1
    return {"workspace": str(workspace), "live_matches_baseline": True,
            "append_only": True, "new_rows": summary,
            "pending_form_reviews": statuses["pending"],
            "uncertain_form_reviews": statuses["needs_review"],
            "total_new_rows": sum(summary.values())}


def promote(live: Path, workspace: Path, backups: Path, *, confirmed=False) -> dict:
    if not confirmed:
        raise ValueError("Promotion requires an explicit --confirm")
    baseline_path, candidate_path = workspace_paths(workspace)
    # Validate before creating a backup, then repeat under write lock.
    preview = plan(live, workspace)
    if preview["pending_form_reviews"]:
        raise RuntimeError(
            f"{preview['pending_form_reviews']} newly imported OCR forms are still pending AI/human review. "
            "Finish resolve/decide-form before promotion."
        )
    if not preview["total_new_rows"]:
        return {**preview, "promoted": False, "reason": "no new data"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backups.mkdir(parents=True, exist_ok=True)
    backup_path = backups / f"before-promotion-{stamp}.db"
    snapshot(live, backup_path)
    backup_path.chmod(0o600)
    try:
        with read_database(baseline_path) as baseline, read_database(candidate_path) as candidate:
            with write_database(live) as production:
                production.execute("BEGIN IMMEDIATE")
                _live_matches_baseline(baseline, production)
                changes = _compare(baseline, candidate)
                for name in TABLE_ORDER:
                    columns, rows = changes[name]
                    if not rows:
                        continue
                    quoted = ", ".join(f'"{column}"' for column in columns)
                    placeholders = ", ".join("?" for _ in columns)
                    sql = f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})'
                    production.executemany(sql, rows.values())
                _integrity(production)
                # write_database commits only after successful validation.
    except Exception:
        # Backups are retained; SQLite rolls back the entire transaction.
        raise
    result = {**preview, "promoted": True, "pre_promotion_backup": str(backup_path),
              "completed_utc": datetime.now(timezone.utc).isoformat()}
    atomic_json(workspace / "promotion.json", result)
    return result
