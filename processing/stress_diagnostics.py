"""Read-only diagnosis of unresolved Russian headword pronunciations.

No relaxation of POS rules, no AI calls, and no writes to the dictionary or
OpenRussian. Writes only an inspectable report to the /work volume.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .openrussian import connect_reference, reference_fingerprint, verify_schema
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
        "blocked": dict(sorted(Counter(row["backfill_blocker"] for row in rows).items())),
        "pos_mismatch_pairs": pair_summaries,
        "ambiguous": [
            {key: r[key] for key in ("lemma", "ruslex_pos", "stress_candidates",
                                     "ruslex_meanings", "reference_glosses")}
            for r in rows if r["backfill_blocker"] == "ambiguous"
        ],
        "yo_disagreements": [
            {key: r[key] for key in ("lemma", "ruslex_pos", "stress_candidates",
                                     "reference_types", "ruslex_meanings", "reference_glosses")}
            for r in rows if r["yo_check"] == "different_spelling"
        ],
        "source_warnings": [
            {key: r[key] for key in ("lemma", "ruslex_pos", "reasons", "stress_candidates")}
            for r in rows if r["backfill_blocker"] == "source_warning"
        ],
        "missing_examples": [
            {key: r[key] for key in ("lemma", "ruslex_pos", "ruslex_meanings")}
            for r in rows if r["backfill_blocker"] == "not_found"
        ][:12],
    }


def diagnose(live: Path, source: Path, work_root: Path) -> dict:
    """Generate one compact terminal summary and one full local JSON report."""
    with read_database(live) as db, connect_reference(source) as ref:
        existing_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_pronunciations'"
        ).fetchone()
        existing = (
            {r[0] for r in db.execute("SELECT DISTINCT lexeme_id FROM lexeme_pronunciations")}
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
        fingerprint = reference_fingerprint(source)

    cases: list[dict] = []
    for row in audit:
        refs = [value for value in row["reference_ids"].split(",") if value]
        cases.append({
            "lexeme_id": row["lexeme_id"],
            "lemma": row["lemma"],
            "ruslex_pos": row["pos"],
            "human_status": statuses[row["lexeme_id"]],
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
        })

    # Hidden means excluded from normal dictionary browsing, but it is not
    # a deletion or an assertion that the entry is a proper name.
    visible_cases = [row for row in cases if row["human_status"] != "hidden"]
    hidden_cases = [row for row in cases if row["human_status"] == "hidden"]
    overview = _summaries(cases)
    visible = _summaries(visible_cases)
    hidden = _summaries(hidden_cases)
    visible_ids = {lexeme_id for lexeme_id, status in statuses.items()
                   if status != "hidden"}
    hidden_ids = set(statuses) - visible_ids
    visibility = {
        "visible": {
            "headwords": len(visible_ids),
            "stored_pronunciations": len(existing & visible_ids),
            "unresolved": len(visible_cases),
            "blocked": visible["blocked"],
        },
        "hidden": {
            "headwords": len(hidden_ids),
            "stored_pronunciations": len(existing & hidden_ids),
            "unresolved": len(hidden_cases),
            "blocked": hidden["blocked"],
        },
        "unresolved_by_review_status": dict(sorted(
            Counter(row["human_status"] for row in cases).items()
        )),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory = work_root / "stress_diagnostics" / stamp
    directory.mkdir(parents=True, exist_ok=False)
    report = directory / "unresolved_headwords.json"
    atomic_json(report, {
        "source_sha256": fingerprint,
        "already_have_pronunciations": len(existing),
        **overview,
        "visibility": visibility,
        "visible_priority": visible,
        "hidden_summary": hidden,
        "all_cases": cases,
        "data_mutation": "none",
    })
    # The terminal is an actionable, visible-only queue. The JSON preserves
    # every hidden entry and the original all-entry diagnostic for auditing.
    return {
        "unresolved_count": len(cases),
        "already_have_pronunciations": len(existing),
        "reference_sha256": fingerprint,
        "report": str(report),
        "visibility": visibility,
        "blocked": overview["blocked"],
        "blocked_all": overview["blocked"],
        "pos_mismatch_pairs": [
            {**row, "examples": row["examples"][:2]}
            for row in visible["pos_mismatch_pairs"][:18]
        ],
        "ambiguous": visible["ambiguous"][:13],
        "yo_disagreements": visible["yo_disagreements"],
        "source_warnings": visible["source_warnings"][:11],
        "visible_missing_examples": visible["missing_examples"],
        "hidden_missing_examples": hidden["missing_examples"][:8],
        "data_mutation": "none",
    }
