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
    ReferenceWord, candidate_words, lookup_key, plain_spelling, pos_code, match_capitalization, word_rows,
)
from .storage import atomic_json

FIELDS = (
    "lexeme_id", "lemma", "pos", "status", "proposed_spelling",
    "stress_candidates", "reference_ids", "reference_types", "reasons",
    "yo_check", "safe_backfill", "backfill_blocker",
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
        # Malformed OpenRussian records are evidence for review, not a reason
        # to abort the audit of every other lexeme.
        aligned_forms = []
        extra_warnings = []
        for word in candidates:
            try:
                aligned_forms.append(match_capitalization(word.stressed, spelling))
            except ValueError:
                extra_warnings.append("reference stress characters do not align with lemma")
        stress_forms = sorted(set(aligned_forms))
        clean_forms = sorted({plain_spelling(value) for value in stress_forms})
        warnings = sorted({warning for w in candidates for warning in w.warnings}
                          | set(extra_warnings))
        # Ё is audited independently of ambiguity and source warnings.
        yo_variants = {w.spelling.casefold() for w in all_matches}
        yo_check = "different_spelling" if any(
            value != spelling.casefold() for value in yo_variants
        ) else "same_spelling" if any("ё" in value for value in yo_variants) else "none"
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

        # A deterministic backfill must have an unambiguous validated reading,
        # matching ё spelling, and known matching reference POS.
        compatible_pos = bool(candidates) and all(
            pos_code(w.word_type) == {"INFN": "VERB", "ADJS": "ADJF", "COMP": "ADJF"}.get(lexeme["pos"], lexeme["pos"])
            for w in candidates
        )
        safe_backfill = (status == "candidate" and yo_check != "different_spelling"
                         and compatible_pos and bool(stress_forms))
        backfill_blocker = (
            "" if safe_backfill else
            "review_yo" if status == "candidate" and yo_check == "different_spelling" else
            "unverified_reference_pos" if status == "candidate" and not compatible_pos else
            "no_usable_stress" if status == "candidate" and not stress_forms else status
        )

        rows.append({
            "lexeme_id": lexeme["id"], "lemma": lexeme["lemma"],
            "pos": lexeme["pos"], "status": status,
            "proposed_spelling": clean_forms[0] if status in ("candidate", "yo_review") else "",
            "stress_candidates": " | ".join(stress_forms),
            "reference_ids": ",".join(w.word_id for w in candidates),
            "reference_types": " | ".join(sorted({w.word_type for w in candidates})),
            "reasons": "; ".join(reasons),
            "yo_check": yo_check,
            "safe_backfill": safe_backfill,
            "backfill_blocker": backfill_blocker,
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
