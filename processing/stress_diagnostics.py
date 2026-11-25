"""Read-only diagnosis of unresolved Russian headword pronunciations.

No relaxation of POS rules, no AI calls, and no writes to the dictionary or
OpenRussian. Writes only an inspectable report to the /work volume.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .openrussian import (connect_reference, match_capitalization, reference_fingerprint,
                         verify_schema, word_rows)
from .reference_audit import audit_entries
from .storage import atomic_json, read_database


def _sense_previews(db: sqlite3.Connection, lexeme_ids: list[int]) -> dict[int, list[str]]:
    if not lexeme_ids:
        return {}
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='senses'"
    ).fetchone():
        return {}
    previews: dict[int, list[str]] = defaultdict(list)
    for start in range(0, len(lexeme_ids), 400):
        batch = lexeme_ids[start:start + 400]
        params = ",".join("?" for _ in batch)
        for row in db.execute(
            f"""SELECT lexeme_id, meaning FROM senses
                WHERE active=1 AND lexeme_id IN ({params})
                ORDER BY id""", batch
        ):
            if row["meaning"] and len(previews[row["lexeme_id"]]) < 2:
                previews[row["lexeme_id"]].append(str(row["meaning"])[:160])
    return dict(previews)


def _english_glosses(reference: sqlite3.Connection, reference_ids: list[str]) -> dict[str, list[str]]:
    if not reference_ids or not verify_schema(reference)["translations"]:
        return {}
    previews: dict[str, list[str]] = defaultdict(list)
    for start in range(0, len(reference_ids), 400):
        batch = reference_ids[start:start + 400]
        params = ",".join("?" for _ in batch)
        for row in reference.execute(
            f"""SELECT word_id, tl FROM translations
                WHERE lang='en' AND word_id IN ({params})
                ORDER BY rowid""", batch
        ):
            key = str(row["word_id"])
            value = str(row["tl"] or "").strip()
            if value and value not in previews[key] and len(previews[key]) < 2:
                previews[key].append(value[:160])
    return dict(previews)


def _reading_options(row: dict, references: dict, glosses: dict) -> list[dict]:
    """Keep the meanings of distinct stressed readings separate.

    OpenRussian POS labels and translations belong to each source record,
    NOT to a union of possible readings. Never choose a reading here.
    """
    grouped: dict[str, dict] = {}
    for word_id in row["reference_ids"].split(","):
        word = references.get(word_id)
        if word is None:
            continue
        warnings = list(word.warnings)
        try:
            reading = match_capitalization(word.stressed, row["lemma"])
        except ValueError:
            reading = word.stressed
            warnings.append("reference spelling cannot be aligned")
        option = grouped.setdefault(reading, {
            "reading": reading,
            "reference_ids": [],
            "reference_types": [],
            "reference_glosses": [],
            "source_warnings": [],
        })
        option["reference_ids"].append(word_id)
        if word.word_type not in option["reference_types"]:
            option["reference_types"].append(word.word_type)
        for gloss in glosses.get(word_id, []):
            if gloss not in option["reference_glosses"]:
                option["reference_glosses"].append(gloss)
        for warning in warnings:
            if warning not in option["source_warnings"]:
                option["source_warnings"].append(warning)
    return sorted(grouped.values(), key=lambda item: item["reading"])


def _summaries(rows: list[dict], limit_per_pair: int = 3) -> dict:
    pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["backfill_blocker"] == "unverified_reference_pos":
            pairs[(row["ruslex_pos"], row["reference_types"])].append(row)
    pair_summaries = [
        {"ruslex_pos": pos, "openrussian_type": source_type,
         "count": len(group),
         "examples": [{"lemma": item["lemma"],
                       "reading": item["stress_candidates"],
                       "ruslex_meanings": item["ruslex_meanings"],
                       "reference_glosses": item["reference_glosses"]}
                      for item in group[:limit_per_pair]]}
        for (pos, source_type), group in sorted(
            pairs.items(), key=lambda item: (-len(item[1]), item[0])
        )
    ]
    return {
        "unresolved_count": len(rows),
        "blocked": dict(sorted(Counter(
            row["backfill_blocker"] for row in rows if row["backfill_blocker"]
        ).items())),
        "eligible_for_import": dict(sorted(Counter(
            row["backfill_method"] for row in rows if row["backfill_method"]
        ).items())),
        "pos_mismatch_pairs": pair_summaries,
        "ambiguous": [
            {key: r[key] for key in ("lexeme_id", "lemma", "ruslex_pos", "stress_candidates",
                                     "ruslex_meanings", "reference_glosses", "reading_options")}
            for r in rows if r["backfill_blocker"] == "ambiguous"
        ],
        "yo_disagreements": [
            {key: r[key] for key in ("lexeme_id", "lemma", "ruslex_pos", "stress_candidates",
                                     "reference_types", "ruslex_meanings", "reference_glosses", "reading_options")}
            for r in rows if r["yo_check"] == "different_spelling"
        ],
        "source_warnings": [
            {key: r[key] for key in ("lexeme_id", "lemma", "ruslex_pos", "reasons", "stress_candidates", "reading_options")}
            for r in rows if r["backfill_blocker"] == "source_warning"
        ],
        "missing_examples": [
            {key: r[key] for key in ("lexeme_id", "lemma", "ruslex_pos", "ruslex_meanings")}
            for r in rows if r["backfill_blocker"] == "not_found"
        ],
    }


def diagnose(live: Path, source: Path, work_root: Path) -> dict:
    """Generate one compact terminal summary and one full local JSON report."""
    with read_database(live) as db, connect_reference(source) as ref:
        existing_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_pronunciations'"
        ).fetchone()
        existing = (
            {r[0] for r in db.execute(
                """SELECT DISTINCT p.lexeme_id FROM lexeme_pronunciations p
                   JOIN lexemes l ON l.id=p.lexeme_id
                   WHERE l.entry_type='word' AND l.human_status != 'hidden'"""
            )}
            if existing_table else set()
        )
        statuses = {
            row["id"]: row["human_status"]
            for row in db.execute(
                "SELECT id, human_status FROM lexemes WHERE entry_type='word'"
            )
        }
        audit = [r for r in audit_entries(ref, db) if r["lexeme_id"] not in existing]
        meanings = _sense_previews(db, [r["lexeme_id"] for r in audit])
        ids = list(dict.fromkeys(
            reference_id
            for row in audit
            for reference_id in row["reference_ids"].split(",")
            if reference_id
        ))
        glosses = _english_glosses(ref, ids)
        wanted_ids = set(ids)
        # One scan over source headwords, not a full dictionary scan per case.
        references = {word.word_id: word for word in word_rows(ref)
                      if word.word_id in wanted_ids}
        fingerprint = reference_fingerprint(source)

    cases: list[dict] = []
    for row in audit:
        refs = [value for value in row["reference_ids"].split(",") if value]
        cases.append({
            "lexeme_id": row["lexeme_id"],
            "lemma": row["lemma"],
            "ruslex_pos": row["pos"],
            "human_status": statuses[row["lexeme_id"]],
            "backfill_method": row["backfill_method"],
            "status": row["status"],
            "backfill_blocker": row["backfill_blocker"],
            "stress_candidates": row["stress_candidates"],
            "reference_types": row["reference_types"],
            "reference_ids": refs,
            "reference_glosses": list(dict.fromkeys(
                meaning for reference_id in refs for meaning in glosses.get(reference_id, [])
            ))[:4],
            "ruslex_meanings": meanings.get(row["lexeme_id"], []),
            "yo_check": row["yo_check"],
            "reasons": row["reasons"],
            "reading_options": _reading_options(row, references, glosses),
        })

    # The active dictionary is the only coverage denominator. Hidden entries
    # are logically deleted and are not in audit_entries() or this report.
    active_ids = {
        lexeme_id for lexeme_id, status in statuses.items()
        if status != "hidden"
    }
    overview = _summaries(cases)
    coverage = {
        "headwords": len(active_ids),
        "stored_pronunciations": len(existing),
        "unresolved": len(cases),
        "blocked": overview["blocked"],
        "eligible_for_import": overview["eligible_for_import"],
        "coverage_pct": round(100 * len(existing) / len(active_ids), 1)
        if active_ids else 100.0,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory = work_root / "stress_diagnostics" / stamp
    directory.mkdir(parents=True, exist_ok=False)
    report = directory / "unresolved_headwords.json"
    atomic_json(report, {
        "source_sha256": fingerprint,
        "already_have_pronunciations": len(existing),
        **overview,
        "active_dictionary": coverage,
        "all_cases": cases,
        "data_mutation": "none",
    })
    return {
        "active_dictionary": coverage,
        "unresolved_count": len(cases),
        "already_have_pronunciations": len(existing),
        "reference_sha256": fingerprint,
        "report": str(report),
        "blocked": overview["blocked"],
        "eligible_for_import": overview["eligible_for_import"],
        "pos_mismatch_pairs": [
            {**row, "examples": row["examples"][:2]}
            for row in overview["pos_mismatch_pairs"][:18]
        ],
        "ambiguous": overview["ambiguous"][:13],
        "yo_disagreements": overview["yo_disagreements"],
        "source_warnings": overview["source_warnings"][:11],
        "missing_examples": overview["missing_examples"],
        "data_mutation": "none",
    }
