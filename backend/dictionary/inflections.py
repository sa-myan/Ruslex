"""Read-only access to optionally installed morphological paradigms.

Actual OCR attestations remain in lexeme_pages; generated forms are not
misrepresented as textbook occurrences or as stress-verified readings.
"""
from __future__ import annotations

from django.db import connections

from .query_helpers import LEXICON, legacy_rows


def installed() -> bool:
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexeme_forms'"
        )
        return cursor.fetchone() is not None


def for_entry(word_id: int) -> list[dict]:
    if not installed():
        return []
    return legacy_rows(
        """SELECT f.form,f.grammemes,f.source FROM lexeme_forms f
           JOIN lexemes l ON l.id=f.lexeme_id
           WHERE f.lexeme_id=%s
             AND f.lemma_at_generation=l.lemma AND f.pos_at_generation=l.pos
           ORDER BY f.form_key,f.form,f.grammemes""",
        [word_id],
    )


def ids_matching(form_key: str, permitted: set[int]) -> set[int]:
    if not form_key or not permitted or not installed():
        return set()
    # No hidden entries: IDs come from the caller's already filtered queryset.
    candidates = legacy_rows(
        """SELECT DISTINCT f.lexeme_id FROM lexeme_forms f
           JOIN lexemes l ON l.id=f.lexeme_id
           WHERE f.form_key=%s
             AND f.lemma_at_generation=l.lemma AND f.pos_at_generation=l.pos""",
        [form_key],
    )
    return {row["lexeme_id"] for row in candidates if row["lexeme_id"] in permitted}
