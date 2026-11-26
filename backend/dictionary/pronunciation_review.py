"""Small permission-gated pronunciation queue independent of lexeme review.

No OpenRussian source data or automated AI decisions are needed by the web app.
The queue includes active words and abbreviations with no stored readings.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.db import connections, transaction

from .query_helpers import LEXICON, legacy_rows


def installed() -> bool:
    with connections[LEXICON].cursor() as cursor:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name='pronunciation_review_queue'")
        return cursor.fetchone() is not None


def _queue_conditions(queue: str) -> str:
    if queue not in {"pending", "deferred", "all"}:
        raise ValueError("Unknown pronunciation queue")
    if queue == "pending":
        return " AND q.lexeme_id IS NULL"
    if queue == "deferred":
        return " AND q.lexeme_id IS NOT NULL"
    return ""


def _eligible_sql(queue: str) -> str:
    """Only unresolved active entries are candidates, never the hidden lexicon."""
    return (
        "FROM lexemes l "
        "LEFT JOIN pronunciation_review_queue q ON q.lexeme_id=l.id "
        "WHERE l.entry_type IN ('word','abbreviation') "
        "AND l.human_status!='hidden' "
        "AND NOT EXISTS(SELECT 1 FROM lexeme_pronunciations p WHERE p.lexeme_id=l.id)"
        + _queue_conditions(queue)
    )


def next_entry(queue: str = "pending", after: int = 0) -> dict:
    if type(after) is not int or after < 0:
        raise ValueError("Invalid pronunciation review cursor")
    if not installed():
        raise RuntimeError("Pronunciation review queue is not initialized")
    where = _eligible_sql(queue)
    total = legacy_rows("SELECT COUNT(*) AS n " + where)[0]["n"]
    rows = legacy_rows(
        "SELECT l.id, q.note, q.lexeme_id AS deferred_id " + where + " AND l.id > %s ORDER BY l.id LIMIT 1",
        [after],
    )
    if not rows:
        rows = legacy_rows("SELECT l.id,q.note,q.lexeme_id AS deferred_id " + where + " ORDER BY l.id LIMIT 1")
    if not rows:
        return {"entry": None, "total": total, "note": "", "deferred": False}
    from .query_detail import detail
    return {
        "entry": detail(rows[0]["id"]),
        "total": total,
        "note": rows[0]["note"] or "",
        "deferred": rows[0]["deferred_id"] is not None,
    }


@transaction.atomic(using=LEXICON)
def defer(word_id: int, note: object, deferred: object) -> dict:
    if not installed():
        raise RuntimeError("Pronunciation review queue is not initialized")
    if type(deferred) is not bool:
        raise ValueError("deferred must be a boolean")
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("Review note must be text of at most 1000 characters")
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            """SELECT 1 FROM lexemes WHERE id=%s
               AND entry_type IN ('word','abbreviation') AND human_status!='hidden'""",
            [word_id],
        )
        if cursor.fetchone() is None:
            raise LookupError("Entry is unavailable for pronunciation review")
        if deferred:
            cursor.execute(
                "SELECT 1 FROM lexeme_pronunciations WHERE lexeme_id=%s",
                [word_id],
            )
            if cursor.fetchone() is not None:
                raise ValueError("Entry already has a pronunciation")
            cursor.execute(
                """INSERT INTO pronunciation_review_queue(lexeme_id,note,deferred_at)
                   VALUES(%s,%s,%s)
                   ON CONFLICT(lexeme_id) DO UPDATE SET note=excluded.note,
                       deferred_at=excluded.deferred_at""",
                [word_id, note.strip(), datetime.now(timezone.utc).isoformat()],
            )
        else:
            cursor.execute(
                "DELETE FROM pronunciation_review_queue WHERE lexeme_id=%s",
                [word_id],
            )
    return {"lexeme_id": word_id, "deferred": deferred,
            "note": note.strip() if deferred else ""}
