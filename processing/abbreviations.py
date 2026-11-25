"""Abbreviation category migration, deterministic discovery and safe classification.

Entry type is orthogonal to part of speech: МГУ and вуз may both be nouns.
Unknown all-cap tokens need context and model review; they are not automatically
abbreviations, since Cyrillic book headings are frequently uppercase.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .pronunciations import _backup, _check
from .storage import read_database, snapshot, write_database

# Deliberately a high-precision set, not a general all-uppercase rule.
# Stored Ruslex lemmas are case-folded; names and headings must not be
# inferred as abbreviations from their lost capitalization.
KNOWN_ABBREVIATIONS = frozenset("""
мгу сша ссср рф оон ес сми мвд фсб кгб мчс ржд гибдд гаи
тв жкх нпп аэс гэс тэс тэц вуз загс нии пту спб эгэ огэ
снг рсфср рнк ввэр мкс сэс жк пво пдд
""".split())
DEFINITION_CUE = re.compile(
    r"\b(?:abbreviation|abbreviated|acronym|initialism|"
    r"stands for|short for|shortened form|abbrev\.)\b", re.IGNORECASE,
)
CHECK_OLD = re.compile(
    r"CHECK\s*\(\s*[\x22']?entry_type[\x22']?\s+IN\s*\("
    r"\s*'word'\s*,\s*'expression'\s*\)\s*\)", re.IGNORECASE,
)
CREATE_LEXEMES = re.compile(
    r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\x60\[]?lexemes["\x60\]]?\s*\(',
    re.IGNORECASE,
)


def supports_abbreviations(db: sqlite3.Connection) -> bool:
    ddl = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='lexemes'"
    ).fetchone()
    if not ddl:
        raise RuntimeError("Lexemes table missing")
    return "'abbreviation'" in ddl[0]


def _candidates(db: sqlite3.Connection) -> list[dict]:
    cases = []
    for row in db.execute(
        """SELECT l.id,l.lemma,l.pos,l.human_status,
                  GROUP_CONCAT(s.meaning, '; ') AS meanings
           FROM lexemes l LEFT JOIN senses s
             ON s.lexeme_id=l.id AND s.active=1
           WHERE l.entry_type='word' AND l.human_status!='hidden'
           GROUP BY l.id ORDER BY l.id"""
    ):
        name = row["lemma"].casefold().replace("ё", "е")
        meanings = str(row["meanings"] or "")
        known = name in KNOWN_ABBREVIATIONS
        definitional = bool(DEFINITION_CUE.search(meanings))
        if known or definitional:
            cases.append({
                "id": row["id"], "lemma": row["lemma"], "pos": row["pos"],
                "meanings": meanings[:260],
                "reason": "known_abbreviation" if known else "meaning_suggests_abbreviation",
                "automatic": known,
            })
    return cases


def plan(live: Path) -> dict:
    with read_database(live) as db:
        _check(db)
        items = _candidates(db)
        counts = dict(Counter(row["reason"] for row in items))
        types = dict(Counter(row["entry_type"] for row in db.execute(
            "SELECT entry_type FROM lexemes WHERE human_status!='hidden'"
        )))
        return {
            "schema_ready": supports_abbreviations(db),
            "current_active_entry_types": types,
            "automatic_candidates": [row for row in items if row["automatic"]],
            "review_candidates": [row for row in items if not row["automatic"]],
            "counts": counts,
            "data_mutation": "none",
        }


def initialize(live: Path, backups: Path) -> dict:
    """Rebuild only lexemes, preserving its exact columns and all other tables.

    SQLite cannot change a CHECK constraint using ALTER TABLE; foreign keys
    must be disabled before the isolated transaction begins, then checked
    before commit. All user indexes and triggers on lexemes are restored.
    """
    with read_database(live) as check:
        _check(check)
        if supports_abbreviations(check):
            return {"schema_ready": True, "changed": False}
        original = check.execute(
            "SELECT sql FROM sqlite_master WHERE name='lexemes' AND type='table'"
        ).fetchone()[0]
        if len(CHECK_OLD.findall(original)) != 1:
            raise RuntimeError("Unexpected entry_type constraint; migration aborted")
        if not CREATE_LEXEMES.match(original):
            raise RuntimeError("Unexpected lexemes DDL; migration aborted")
        objects = [
            (row["type"], row["name"], row["sql"])
            for row in check.execute(
                """SELECT type,name,sql FROM sqlite_master
                   WHERE tbl_name='lexemes' AND type IN ('trigger','index')
                     AND sql IS NOT NULL ORDER BY type,name"""
            )
        ]
        before_rows = [tuple(row) for row in check.execute(
            "SELECT * FROM lexemes ORDER BY id"
        )]
    backup = _backup(live, backups, "abbreviation-schema")
    db = sqlite3.connect(f"file:{live.resolve()}?mode=rw", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        now_ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='lexemes'").fetchone()[0]
        if now_ddl != original:
            raise RuntimeError("Lexemes schema changed while preparing migration")
        replacement = "CHECK(entry_type IN ('word','expression','abbreviation'))"
        create_sql = CHECK_OLD.sub(replacement, original)
        create_sql = CREATE_LEXEMES.sub(
            'CREATE TABLE "__ruslex_new_lexemes" (', create_sql, count=1
        )
        db.execute(create_sql)
        db.execute(
            'INSERT INTO "__ruslex_new_lexemes" SELECT * FROM lexemes'
        )
        db.execute("DROP TABLE lexemes")
        db.execute('ALTER TABLE "__ruslex_new_lexemes" RENAME TO lexemes')
        for _, _, definition in objects:
            db.execute(definition)
        after_rows = [tuple(row) for row in db.execute(
            "SELECT * FROM lexemes ORDER BY id"
        )]
        if before_rows != after_rows:
            raise RuntimeError("Lexeme contents changed in abbreviation migration")
        _check(db)
        db.commit()
        db.execute("PRAGMA foreign_keys=ON")
        _check(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"schema_ready": True, "changed": True, "backup": str(backup),
            "preserved_headwords": len(before_rows), "data_mutation": "schema_extended"}


def categorize(live: Path, backups: Path) -> dict:
    preview = plan(live)
    if not preview["schema_ready"]:
        raise RuntimeError("Run abbreviations init --confirm first")
    if not preview["automatic_candidates"]:
        return {**preview, "reclassified": 0, "data_mutation": "none"}
    backup = _backup(live, backups, "abbreviation-classification")
    with write_database(live) as db:
        db.execute("BEGIN IMMEDIATE")
        changes = [row["id"] for row in _candidates(db) if row["automatic"]]
        if changes != [row["id"] for row in preview["automatic_candidates"]]:
            raise RuntimeError("Abbreviation candidates changed during classification")
        db.executemany(
            """UPDATE lexemes SET entry_type='abbreviation'
               WHERE id=? AND entry_type='word' AND human_status!='hidden'""",
            [(id_,) for id_ in changes],
        )
        _check(db)
    return {"reclassified": len(changes),
            "entries": preview["automatic_candidates"],
            "review_candidates": preview["review_candidates"],
            "backup": str(backup), "data_mutation": "entry_types_updated"}


def rehearse(live: Path, root: Path) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target = root / "abbreviation_rehearsals" / stamp
    target.mkdir(parents=True, exist_ok=False)
    copy = target / "lexicon.db"
    snapshot(live, copy)
    first = initialize(copy, target / "backups")
    classification = categorize(copy, target / "backups")
    second = initialize(copy, target / "backups")
    with read_database(copy) as db:
        _check(db)
        count = db.execute(
            "SELECT COUNT(*) FROM lexemes WHERE entry_type='abbreviation'"
        ).fetchone()[0]
    return {
        "success": True, "production_modified": False,
        "rehearsal_directory": str(target),
        "migration": first, "idempotent_schema": not second["changed"],
        "classification": classification, "abbreviations_total": count,
    }
