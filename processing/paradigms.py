"""Offline Russian inflection paradigms, separate from attested OCR surfaces.

Only morphology-derived forms with unambiguous paradigm identity are stored.
No fabricated inflected stress: stress is kept at the headword level.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .pronunciations import _backup, _check
from .storage import read_database, snapshot, write_database

WORD = re.compile(r"^[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*$")
ALLOWED_POS = {
    "NOUN": {"NOUN"}, "VERB": {"INFN", "VERB"},
    "ADJF": {"ADJF", "ADJS"}, "NPRO": {"NPRO"}, "NUMR": {"NUMR"},
    "PRTF": {"PRTF", "PRTS"},
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS form_schema_versions(
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO form_schema_versions(version,applied_at)
VALUES (1,datetime('now'));
CREATE TABLE IF NOT EXISTS lexeme_forms(
    id INTEGER PRIMARY KEY,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    form TEXT NOT NULL,
    form_key TEXT NOT NULL,
    grammemes TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'pymorphy3'
        CHECK (source IN ('pymorphy3','manual','openrussian')),
    created_at TEXT NOT NULL,
    UNIQUE(lexeme_id,form,grammemes)
);
CREATE INDEX IF NOT EXISTS idx_lexeme_forms_search ON lexeme_forms(form_key);
CREATE INDEX IF NOT EXISTS idx_lexeme_forms_entry ON lexeme_forms(lexeme_id);
"""


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed
                   if unicodedata.category(char) != "Mn").casefold().replace("ё", "е")


def installed(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_forms'"
    ).fetchone() is not None


def analyzer():
    import pymorphy3
    return pymorphy3.MorphAnalyzer(lang="ru")


def generate(lemma: str, pos: str, morph) -> tuple[list[tuple[str, str]], str]:
    """Return forms, or an explicit reason for abstaining.

    Multiple distinct same-POS morphological paradigms are not combined:
    select the correct paradigm later instead of silently mixing homographs.
    """
    if pos not in ALLOWED_POS:
        return [], "unsupported_pos"
    if not WORD.fullmatch(lemma):
        return [], "invalid_headword"
    options = []
    for parse in morph.parse(lemma):
        if parse.tag.POS not in ALLOWED_POS[pos]:
            continue
        if fold(parse.normal_form) != fold(lemma):
            continue
        forms = set()
        for item in parse.lexeme:
            form = unicodedata.normalize("NFC", str(item.word))
            if not WORD.fullmatch(form):
                continue
            grammemes = ",".join(sorted(str(g) for g in item.tag.grammemes))
            forms.add((form, grammemes))
        if forms:
            options.append(frozenset(forms))
    if not options:
        return [], "no_matching_analysis"
    unique = set(options)
    if len(unique) > 1:
        return [], "multiple_paradigms"
    forms = sorted(next(iter(unique)), key=lambda row: (fold(row[0]), row[0], row[1]))
    if len({form for form, _ in forms}) < 2:
        return [], "invariable"
    return forms, ""


def _words(db: sqlite3.Connection, lexeme_ids: set[int] | None = None):
    for row in db.execute(
        """SELECT id,lemma,pos FROM lexemes
           WHERE entry_type='word' AND human_status!='hidden' ORDER BY id"""
    ):
        if lexeme_ids is None or row["id"] in lexeme_ids:
            yield row


def _insert(db: sqlite3.Connection, morph, lexeme_ids: set[int] | None = None) -> dict:
    if not installed(db):
        raise RuntimeError("Form schema missing; run forms init --confirm")
    counts = Counter()
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in _words(db, lexeme_ids):
        if db.execute("SELECT 1 FROM lexeme_forms WHERE lexeme_id=?", (row["id"],)).fetchone():
            counts["existing_entries_skipped"] += 1
            continue
        forms, reason = generate(row["lemma"], row["pos"], morph)
        if reason:
            counts[reason] += 1
            continue
        db.executemany(
            """INSERT OR IGNORE INTO lexeme_forms
               (lexeme_id,form,form_key,grammemes,source,created_at)
               VALUES (?,?,?,?,'pymorphy3',?)""",
            [(row["id"], form, fold(form), grammemes, timestamp)
             for form, grammemes in forms],
        )
        counts["entries_generated"] += 1
        counts["forms_added"] += len(forms)
    return dict(counts)


def initialize(live: Path, backups: Path) -> dict:
    with read_database(live) as db:
        _check(db)
        if installed(db):
            return {"installed": True, "changed": False}
    backup = _backup(live, backups, "forms-schema")
    with write_database(live) as db:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        _check(db)
    return {"installed": True, "changed": True, "backup": str(backup),
            "schema_version": 1}


def plan(live: Path, morph=None) -> dict:
    """Exact deterministic preview, including abstentions and row count."""
    morph = morph or analyzer()
    with read_database(live) as db:
        _check(db)
        rows = list(_words(db))
        has_table = installed(db)
        existing = (set(r[0] for r in db.execute(
            """SELECT DISTINCT f.lexeme_id FROM lexeme_forms f
               JOIN lexemes l ON l.id=f.lexeme_id
               WHERE l.entry_type='word' AND l.human_status!='hidden'""")) if has_table else set())
    reasons = Counter()
    eligible = 0
    expected_forms = 0
    for row in rows:
        if row["id"] in existing:
            continue
        forms, reason = generate(row["lemma"], row["pos"], morph)
        if reason:
            reasons[reason] += 1
        else:
            eligible += 1
            expected_forms += len(forms)
    return {"schema_installed": has_table, "visible_headwords": len(rows),
            "existing_form_entries": len(existing),
            "eligible_headwords": eligible, "expected_form_rows": expected_forms,
            "skipped": dict(reasons), "data_mutation": "none"}


def backfill(live: Path, backups: Path, morph=None) -> dict:
    morph = morph or analyzer()
    before = plan(live, morph)
    if not before["schema_installed"]:
        raise RuntimeError("Run forms init --confirm first")
    if not before["eligible_headwords"]:
        return {**before, "generated": {}, "data_mutation": "none"}
    backup = _backup(live, backups, "forms-backfill")
    with write_database(live) as db:
        db.execute("BEGIN IMMEDIATE")
        generated = _insert(db, morph)
        _check(db)
    if generated.get("forms_added", 0) != before["expected_form_rows"]:
        raise RuntimeError("Form generation changed since preview")
    return {**before, "generated": generated,
            "backup": str(backup),
            "data_mutation": "forms_inserted" if generated.get("forms_added", 0) else "none"}


def for_new_lexemes(db: sqlite3.Connection, lexeme_ids: set[int], morph=None) -> dict:
    """Generate forms in the SAME transaction as first book promotion."""
    if not lexeme_ids or not installed(db):
        return {}
    return _insert(db, morph or analyzer(), lexeme_ids)


def rehearse(live: Path, work: Path, morph=None) -> dict:
    root = work / "form_rehearsals" / datetime.now(timezone.utc).strftime(
        "%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True, exist_ok=False)
    target = root / "lexicon.db"
    snapshot(live, target)
    with read_database(target) as db:
        before = {
            table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("lexemes", "senses", "lexeme_pages")
        }
    schema = initialize(target, root / "backups")
    first = backfill(target, root / "backups", morph)
    second = backfill(target, root / "backups", morph)
    with read_database(target) as db:
        _check(db)
        after = {
            table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in before
        }
        generated = db.execute("SELECT COUNT(*) FROM lexeme_forms").fetchone()[0]
    if before != after or second["generated"].get("forms_added", 0):
        raise RuntimeError("Forms rehearsal violated original counts or idempotence")
    return {"success": True, "production_modified": False,
            "rehearsal_path": str(root), "schema": schema, "first": first["generated"],
            "second": second["generated"], "forms_total": generated,
            "original_record_counts_unchanged": True}
