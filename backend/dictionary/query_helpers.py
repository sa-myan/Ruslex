"""Shared read-only helpers for legacy SQLite join tables.

Use a dedicated lexicon connection. Every dynamic SQL value is supplied as a
bound parameter; generated placeholder lists come only from a numeric count.
"""

from collections import defaultdict
import math

from django.db import connections

LEXICON = "lexicon"
SQL_BATCH_SIZE = 400  # Below SQLite's traditional 999-variable limit.


def legacy_rows(sql: str, args=()) -> list[dict]:
    """Execute a parameterized SELECT against the lexicon database only."""
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(sql, args)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, values)) for values in cursor.fetchall()]


def one(sql: str, args=()) -> dict:
    return legacy_rows(sql, args)[0]


def paginate(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    page_count = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    return {
        "items": items[offset : offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": page_count,
    }


def _batches(items: list, size: int = SQL_BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _sql_placeholders(count: int) -> str:
    """Only interpolate a known count, never user-supplied SQL fragments."""
    return ",".join(["%s"] * count)


def tags_for_senses(sense_ids: list[int]) -> dict[int, list[dict]]:
    if not sense_ids:
        return {}

    grouped = defaultdict(list)
    unique_ids = list(dict.fromkeys(sense_ids))
    for batch in _batches(unique_ids):
        rows = legacy_rows(
            f"""SELECT st.sense_id, t.id, t.name, t.category
                FROM sense_tags st
                JOIN tags t ON t.id = st.tag_id
                WHERE st.sense_id IN ({_sql_placeholders(len(batch))})
                ORDER BY t.category, t.name""",
            batch,
        )
        for row in rows:
            sense_id = row.pop("sense_id")
            grouped[sense_id].append(row)
    return grouped


def _page_counts(word_ids: list[int]) -> dict[int, int]:
    counts = {}
    for batch in _batches(word_ids):
        rows = legacy_rows(
            f"""SELECT lexeme_id, COUNT(DISTINCT page_id) AS n
                FROM lexeme_pages
                WHERE lexeme_id IN ({_sql_placeholders(len(batch))})
                GROUP BY lexeme_id""",
            batch,
        )
        for row in rows:
            counts[row["lexeme_id"]] = row["n"]
    return counts
