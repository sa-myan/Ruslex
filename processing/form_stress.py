"""Conservative, offline OpenRussian stress enrichment for stored inflected forms.

Uses OpenRussian's optional words_forms table only, anchored to a uniquely
identifiable reference headword (or a previously source-backed reference ID).
Nothing is inferred from endings or from isolated matching surface spellings.
An entire conflicting form key is skipped. Source references stay outside web.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .openrussian import (
    connect_reference, lookup_key, match_capitalization, normalize_accented,
    plain_spelling, pos_code, verify_schema, word_rows, reference_fingerprint,
)
from .paradigms import installed as forms_installed, fold
from .pronunciations import _backup, _check, installed as pronunciation_installed
from .storage import read_database, snapshot, write_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS lexeme_form_stress(
    form_id INTEGER PRIMARY KEY REFERENCES lexeme_forms(id) ON DELETE CASCADE,
    stressed TEXT NOT NULL,
    reference_word_id TEXT NOT NULL,
    reference_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
NORMAL_POS = {"INFN": "VERB", "ADJS": "ADJF", "COMP": "ADJF"}


def installed(db) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_form_stress'"
    ).fetchone() is not None


def initialize(live: Path, backups: Path) -> dict:
    with read_database(live) as db:
        _check(db)
        if not forms_installed(db):
            raise RuntimeError("Generate morphological forms first")
        if installed(db):
            return {"schema_ready": True, "changed": False, "data_mutation": "none"}
    backup = _backup(live, backups, "form-stress-schema")
    with write_database(live) as db:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        _check(db)
    return {"schema_ready": True, "changed": True, "backup": str(backup),
            "data_mutation": "form_stress_schema_added"}


def _proposals(live, reference) -> dict:
    if not forms_installed(live):
        raise RuntimeError("Morphological forms schema is missing")
    available = verify_schema(reference)
    if not available["words_forms"]:
        return {"available": False, "candidates": [], "stats": Counter()}

    # Current generated spellings only; historical rows are not enrichable.
    form_rows = list(live.execute(
        """SELECT f.id, f.lexeme_id, f.form, f.form_key, f.grammemes,
                  l.lemma, l.pos
           FROM lexeme_forms f JOIN lexemes l ON l.id=f.lexeme_id
           WHERE l.human_status!='hidden'
             AND f.lemma_at_generation=l.lemma AND f.pos_at_generation=l.pos
           ORDER BY f.lexeme_id,f.id"""
    ))
    entries = {(row["lexeme_id"], row["lemma"], row["pos"])
               for row in form_rows}
    selected = {}
    wanted = {lookup_key(lemma) for _, lemma, _ in entries}
    reference_by_key = defaultdict(list)
    for word in word_rows(reference):
        if lookup_key(word.bare) in wanted or lookup_key(word.spelling) in wanted:
            reference_by_key[lookup_key(word.bare)].append(word)
            if lookup_key(word.spelling) != lookup_key(word.bare):
                reference_by_key[lookup_key(word.spelling)].append(word)
    pinned = defaultdict(set)
    if pronunciation_installed(live):
        for row in live.execute(
            """SELECT lexeme_id,reference_id FROM lexeme_pronunciations
               WHERE source='openrussian' AND reference_id!=''
                 AND verification IN ('source_backed','verified')"""
        ):
            pinned[row["lexeme_id"]].add(str(row["reference_id"]))

    stats = Counter()
    for lexeme_id, lemma, pos in sorted(entries):
        matches = reference_by_key[lookup_key(lemma)]
        expected = NORMAL_POS.get(pos, pos)
        valid = [word for word in matches
                 if not word.warnings and pos_code(word.word_type) == expected
                 and (word.spelling.casefold() == lemma.casefold()
                      or word.word_id in pinned[lexeme_id])]
        # If a previously vetted OpenRussian word_id exists, it selects the
        # homograph explicitly; otherwise any ambiguity blocks automatic use.
        if pinned[lexeme_id]:
            valid = [word for word in valid if word.word_id in pinned[lexeme_id]]
        if len(valid) != 1:
            stats["ambiguous_or_missing_headword"] += 1
            continue
        selected[lexeme_id] = valid[0].word_id
    accepted_ids = set(selected.values())
    reading_by_word = defaultdict(lambda: defaultdict(set))
    # Scan the optional reference table once, avoiding thousands of slow
    # unindexed lookups in legacy OpenRussian dumps.
    for row in reference.execute("SELECT word_id,form FROM words_forms"):
        word_id = str(row["word_id"])
        if word_id not in accepted_ids:
            continue
        stressed, warnings = normalize_accented(str(row["form"] or ""))
        if warnings:
            stats["reference_form_warning"] += 1
            continue
        reading_by_word[word_id][fold(stressed)].add(stressed)

    previous = set()
    if installed(live):
        previous = {row[0] for row in live.execute(
            "SELECT form_id FROM lexeme_form_stress"
        )}
    candidates = []
    for row in form_rows:
        word_id = selected.get(row["lexeme_id"])
        if not word_id:
            continue
        if row["id"] in previous:
            stats["existing"] += 1
            continue
        readings = reading_by_word[word_id].get(row["form_key"], set())
        if len(readings) != 1:
            stats["missing_or_ambiguous_form"] += 1
            continue
        reading = next(iter(readings))
        if fold(reading) != row["form_key"]:
            stats["form_key_mismatch"] += 1
            continue
        try:
            aligned = match_capitalization(reading, row["form"])
        except ValueError:
            stats["unaligned_form"] += 1
            continue
        # Preserve existing ё. Never replace it with е just because a source
        # flattened the distinction.
        original = plain_spelling(row["form"]).casefold()
        proposed = plain_spelling(aligned).casefold()
        if "ё" in original and proposed != original:
            stats["existing_yo_conflict"] += 1
            continue
        candidates.append((row["id"], aligned, word_id))
    return {"available": True, "candidates": candidates, "stats": stats,
            "headwords_matched": len(selected), "forms_total": len(form_rows)}


def plan(live: Path, reference: Path) -> dict:
    with read_database(live) as db, connect_reference(reference) as ref:
        _check(db)
        result = _proposals(db, ref)
        schema_ready = installed(db)
    return {"schema_ready": schema_ready,
            "reference_forms_available": result["available"],
            "headwords_matched": result.get("headwords_matched", 0),
            "forms_total": result.get("forms_total", 0),
            "safe_candidates": len(result["candidates"]),
            "skipped": dict(result["stats"]),
            "sample": [{"form_id": id_, "stressed": stressed, "reference_id": ref_id}
                       for id_, stressed, ref_id in result["candidates"][:15]],
            "data_mutation": "none"}


def apply(live: Path, reference: Path, backups: Path) -> dict:
    preview = plan(live, reference)
    if not preview["schema_ready"]:
        raise RuntimeError("Run forms stress-init --confirm first")
    if not preview["safe_candidates"]:
        return {**preview, "inserted": 0}
    backup = _backup(live, backups, "form-stress")
    fingerprint = reference_fingerprint(reference)
    with connect_reference(reference) as ref, write_database(live) as db:
        db.execute("BEGIN IMMEDIATE")
        result = _proposals(db, ref)
        candidates = result["candidates"]
        if len(candidates) != preview["safe_candidates"]:
            raise RuntimeError("Inflection stress candidates changed; aborting")
        stamp = datetime.now(timezone.utc).isoformat()
        db.executemany(
            """INSERT INTO lexeme_form_stress
               (form_id,stressed,reference_word_id,reference_fingerprint,created_at)
               VALUES (?,?,?,?,?)""",
            [(form_id, stressed, word_id, fingerprint, stamp)
             for form_id, stressed, word_id in candidates]
        )
        _check(db)
    return {**preview, "inserted": len(candidates),
            "backup": str(backup), "data_mutation": "form_stress_inserted"}


def rehearse(live: Path, reference: Path, work: Path) -> dict:
    root = work / "form_stress_rehearsal" / datetime.now(timezone.utc).strftime(
        "%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True, exist_ok=False)
    copy = root / "lexicon.db"
    snapshot(live, copy)
    before = plan(copy, reference)
    init = initialize(copy, root / "backups")
    first = apply(copy, reference, root / "backups")
    second = apply(copy, reference, root / "backups")
    with read_database(copy) as db:
        _check(db)
    if second["inserted"] or first["inserted"] != before["safe_candidates"]:
        raise RuntimeError("Form stress rehearsal was not idempotent")
    return {"success": True, "production_modified": False,
            "schema": init, "inserted": first["inserted"],
            "second_inserted": second["inserted"], "rehearsal_path": str(root)}
