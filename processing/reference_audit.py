"""Conservative, read-only headword stress and ё audit for Ruslex.

Suggestions are *not* verified dictionary data. The output intentionally does
not modify or propose SQL updates to the production lexicon.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .openrussian import (
    ReferenceWord, candidate_words, lookup_key, plain_spelling, word_rows,
)
from .storage import atomic_json

FIELDS = (
    "lexeme_id", "lemma", "pos", "status", "proposed_spelling",
    "stress_candidates", "reference_ids", "reference_types", "reasons",
)


def audit_entries(reference: sqlite3.Connection, lexicon: sqlite3.Connection) -> list[dict]:
    lexemes = list(lexicon.execute(
        "SELECT id,lemma,pos FROM lexemes WHERE entry_type='word' ORDER BY id"
    ))
    wanted = {lookup_key(row["lemma"]) for row in lexemes}
    reference_by_key: dict[str, list[ReferenceWord]] = defaultdict(list)
    for word in word_rows(reference):
        for key in {lookup_key(word.bare), lookup_key(word.spelling)} & wanted:
            reference_by_key[key].append(word)

    rows: list[dict] = []
    for lexeme in lexemes:
        spelling = plain_spelling(lexeme["lemma"])
        all_matches = reference_by_key[lookup_key(spelling)]
        candidates, pos_filtered = candidate_words(all_matches, lexeme["pos"])
        stress_forms = sorted({w.stressed for w in candidates})
        clean_forms = sorted({w.spelling for w in candidates})
        warnings = sorted({warning for w in candidates for warning in w.warnings})
        reasons = list(warnings)

        if not candidates:
            status = "not_found"
        elif warnings:
            status = "source_warning"
        elif len(stress_forms) > 1 or len(clean_forms) > 1:
            status = "ambiguous"
        elif len(clean_forms) == 1 and clean_forms[0].casefold() != spelling.casefold():
            status = "yo_review"
        else:
            status = "candidate"

        if candidates and not pos_filtered and len(all_matches) > 1:
            reasons.append("reference part of speech not fully distinguishable")
        if status == "yo_review":
            reasons.append("reference suggests a different ё/е spelling; human verification needed")
        if len(candidates) > 1 and len(stress_forms) == 1:
            reasons.append("multiple reference entries share a reading")

        rows.append({
            "lexeme_id": lexeme["id"], "lemma": lexeme["lemma"],
            "pos": lexeme["pos"], "status": status,
            "proposed_spelling": clean_forms[0] if status in ("candidate", "yo_review") else "",
            "stress_candidates": " | ".join(stress_forms),
            "reference_ids": ",".join(w.word_id for w in candidates),
            "reference_types": " | ".join(sorted({w.word_type for w in candidates})),
            "reasons": "; ".join(reasons),
        })
    return rows


def write_report(rows: list[dict], output_directory: Path) -> dict:
    output_directory.mkdir(parents=True, exist_ok=False)
    csv_path = output_directory / "headword_candidates.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    summary = {
        "lexemes_checked": len(rows),
        "status_counts": counts,
        "csv": str(csv_path),
        "warning": "Suggestions only. No Ruslex database rows were changed.",
    }
    atomic_json(output_directory / "summary.json", summary)
    return summary


def suggested_report_path(work: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return work / "reference_reports" / stamp
