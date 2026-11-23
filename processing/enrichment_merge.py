"""Apply validated AI enrichment *additively* to an isolated candidate DB.

Existing senses, tags, notes, aspect, and relations are never rewritten.
Newly discovered relationships are reported as suggestions for manual review.
"""
from __future__ import annotations

import json
from pathlib import Path

from .storage import checked_workspace, read_database, staged_files, write_database, atomic_json
from .taxonomy import seed_tags
from .validation import validate_lexemes, validate_pages, normalized
from .workflow import find_or_add_word, insert_senses


def _staged_lexemes(stage: Path, source: Path):
    with read_database(source) as db:
        known = {row["id"]: dict(row) for row in db.execute(
            "SELECT id,lemma,pos FROM lexemes WHERE human_status='kept' AND entry_type='word'")}
    entries = {}
    for path in staged_files(stage, "lexemes"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = payload.get("input_ids", [])
        if not isinstance(ids, list) or len(set(ids)) != len(ids) or any(i not in known for i in ids):
            raise ValueError(f"Invalid staged lexeme IDs: {path}")
        for item in validate_lexemes(payload, {key: known[key] for key in ids}):
            if item["id"] in entries:
                raise ValueError("Repeated lexeme enrichment output")
            entries[item["id"]] = item
    return known, entries


def _staged_expressions(stage: Path, source: Path):
    with read_database(source) as db:
        pages = {row["id"]: row["markdown"] for row in db.execute("SELECT id,markdown FROM pages")}
    expressions = {}
    for path in staged_files(stage, "pages"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = payload.get("input_ids", [])
        if not isinstance(ids, list) or len(set(ids)) != len(ids) or any(i not in pages for i in ids):
            raise ValueError(f"Invalid staged page IDs: {path}")
        batch = validate_pages(payload, {key: pages[key] for key in ids})
        for expression in batch:
            key = (expression["lemma"].strip().lower(), expression["pos"])
            if key not in expressions:
                expressions[key] = expression
                continue
            # Preserve first proposed definition; collect all real attestations.
            previous = expressions[key]["attestations"]
            recorded = {(item["page_id"], item["surface"]) for item in previous}
            for item in expression["attestations"]:
                if (item["page_id"], item["surface"]) not in recorded:
                    previous.append(item)
                    recorded.add((item["page_id"], item["surface"]))
    return pages, expressions


def apply_enrichment(workspace: Path) -> dict:
    """Safely insert missing senses/expressions in workspace candidate only."""
    stage = workspace / "enrichment"
    source = checked_workspace(stage)
    candidate = workspace / "candidate.db"
    baseline = workspace / "baseline.db"
    known, lexemes = _staged_lexemes(stage, source)
    pages, expressions = _staged_expressions(stage, source)
    if not lexemes and not expressions:
        raise RuntimeError("No validated enrichment batches found")

    with read_database(baseline) as db:
        original_ids = {row[0] for row in db.execute("SELECT id FROM lexemes")}

    suggestions = []
    statistics = {"new_senses_on_entries": 0, "skipped_entries_with_senses": 0,
                  "new_expressions": 0, "expression_attestations": 0,
                  "relationship_suggestions": 0, "followup_component_words": 0}
    missing_words = set()
    with write_database(candidate) as db:
        db.execute("BEGIN IMMEDIATE")
        seed_tags(db)
        for entry_id, item in sorted(lexemes.items()):
            row = db.execute("SELECT id,lemma,pos,entry_type FROM lexemes WHERE id=?",
                             (entry_id,)).fetchone()
            if not row or (row["lemma"], row["pos"], row["entry_type"]) != (
                    known[entry_id]["lemma"], known[entry_id]["pos"], "word"):
                raise RuntimeError(f"Lexeme changed since enrichment snapshot: {entry_id}")
            sense_count = db.execute("SELECT COUNT(*) FROM senses WHERE lexeme_id=?",
                                     (entry_id,)).fetchone()[0]
            if sense_count:
                statistics["skipped_entries_with_senses"] += 1
                continue
            # Do not modify any existing headword fields from the original DB.
            if entry_id not in original_ids:
                db.execute("UPDATE lexemes SET aspect=?,animacy=? WHERE id=?",
                           (item["aspect"], item["animacy"], entry_id))
            insert_senses(db, entry_id, item["senses"])
            statistics["new_senses_on_entries"] += 1
            for relation in item.get("relations", []):
                suggestions.append({"lexeme_id": entry_id, **relation})
        for (lemma, pos), expression in sorted(expressions.items()):
            row = db.execute("SELECT id,entry_type FROM lexemes WHERE lemma=? AND pos=?",
                             (lemma, pos)).fetchone()
            if row and row["entry_type"] != "expression":
                raise ValueError(f"Expression conflicts with a word entry: {lemma}/{pos}")
            if row:
                expression_id = row["id"]
            else:
                expression_id = db.execute("""INSERT INTO lexemes
                    (lemma,pos,entry_type,human_status) VALUES(?,?,'expression','followup')""",
                    (lemma, pos)).lastrowid
                insert_senses(db, expression_id, expression["senses"])
                for position, component in enumerate(expression["components"], start=1):
                    word_id = find_or_add_word(db, component["lemma"], component["pos"], missing_words)
                    db.execute("""INSERT INTO expression_components
                        (expression_id,word_id,position,surface) VALUES (?,?,?,?)""",
                        (expression_id, word_id, position, component["surface"]))
                statistics["new_expressions"] += 1
            for attestation in expression["attestations"]:
                page_id, surface = attestation["page_id"], attestation["surface"]
                current = db.execute("SELECT markdown FROM pages WHERE id=?", (page_id,)).fetchone()
                if not current or current[0] != pages[page_id] or normalized(surface) not in normalized(current[0]):
                    raise RuntimeError("Expression attestation changed since model analysis")
                cursor = db.execute("""INSERT OR IGNORE INTO lexeme_pages
                    (lexeme_id,page_id,surface,context,count) VALUES(?,?,?,?,1)""",
                    (expression_id, page_id, surface, surface))
                statistics["expression_attestations"] += int(cursor.rowcount > 0)
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Enrichment introduced foreign-key violations")
    statistics["relationship_suggestions"] = len(suggestions)
    statistics["followup_component_words"] = len(missing_words)
    atomic_json(workspace / "enrichment_review.json", {
        "statistics": statistics, "unapplied_relationships": suggestions,
        "component_words_for_followup": sorted(missing_words),
        "policy": "Existing senses/notes/links untouched; relations require manual review",
    })
    return statistics
