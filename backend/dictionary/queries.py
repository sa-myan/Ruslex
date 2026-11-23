"""Stable read-only dictionary query interface.

The API and smoke tests continue importing from ``dictionary.queries``.
Implementation is separated into focused modules:
- query_search.py: filtering, relevance, results previews
- query_detail.py: entry serialization, including notes and relationships
- query_helpers.py: parameterized legacy SQLite helpers
This file retains references, books, tags, statistics, and review navigation.
"""

from .catalog import STATUSES
from .models import Book, Lexeme, Tag
from .query_detail import detail
from .query_helpers import LEXICON, legacy_rows, one, paginate, tags_for_senses
from .query_search import search, summaries


def _check_entry_exists(word_id: int) -> None:
    if not Lexeme.objects.using(LEXICON).filter(pk=word_id).exists():
        raise LookupError("Entry not found")


def references(
    word_id: int,
    page: int = 1,
    size: int = 40,
    book_id: int | None = None,
    pdf_page: int | None = None,
) -> dict:
    _check_entry_exists(word_id)
    conditions = ["lp.lexeme_id=%s"]
    arguments = [word_id]
    if book_id:
        conditions.append("p.book_id=%s")
        arguments.append(book_id)
    if pdf_page:
        conditions.append("p.pdf_page=%s")
        arguments.append(pdf_page)

    rows = legacy_rows(
        """SELECT b.id book_id, b.title, b.edition, p.id page_id, p.pdf_page,
                  p.printed_page, lp.surface, lp.context, lp.count
           FROM lexeme_pages lp
           JOIN pages p ON p.id = lp.page_id
           JOIN books b ON b.id = p.book_id WHERE """
        + " AND ".join(conditions)
        + " ORDER BY b.title, b.id, p.pdf_page, lp.surface",
        arguments,
    )
    return paginate(rows, page, size)


def reference_pages(word_id: int, page: int = 1, size: int = 60) -> dict:
    _check_entry_exists(word_id)
    rows = legacy_rows(
        """SELECT b.id book_id, b.title, b.edition, p.id page_id, p.pdf_page,
                  p.printed_page, SUM(lp.count) occurrence_count
           FROM lexeme_pages lp
           JOIN pages p ON p.id = lp.page_id
           JOIN books b ON b.id = p.book_id
           WHERE lp.lexeme_id=%s GROUP BY p.id
           ORDER BY b.title, b.id, p.pdf_page""",
        [word_id],
    )
    return paginate(rows, page, size)


def books() -> list[dict]:
    counts = {
        row["book_id"]: row["n"]
        for row in legacy_rows("SELECT book_id, COUNT(*) n FROM pages GROUP BY book_id")
    }
    return [
        {
            "id": book.id,
            "title": book.title,
            "edition": book.edition,
            "page_count": counts.get(book.id, 0),
        }
        for book in Book.objects.using(LEXICON).order_by("title", "edition", "id")
    ]


def tags() -> list[dict]:
    counts = {
        row["id"]: row
        for row in legacy_rows(
            """SELECT t.id,
                      COUNT(DISTINCT CASE WHEN s.active=1 THEN s.lexeme_id END) word_count,
                      COUNT(st.sense_id) sense_count
               FROM tags t
               LEFT JOIN sense_tags st ON st.tag_id=t.id
               LEFT JOIN senses s ON s.id=st.sense_id
               GROUP BY t.id"""
        )
    }
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "category": tag.category,
            "word_count": counts[tag.id]["word_count"],
            "sense_count": counts[tag.id]["sense_count"],
        }
        for tag in Tag.objects.using(LEXICON).order_by("category", "name")
    ]


def stats() -> dict:
    tables = ("books", "pages", "lexemes", "senses", "examples", "patterns")
    return {
        "counts": {table: one(f"SELECT COUNT(*) n FROM {table}")["n"] for table in tables},
        "word_status": {
            row["human_status"]: row["n"]
            for row in legacy_rows("SELECT human_status, COUNT(*) n FROM lexemes GROUP BY human_status")
        },
        "review_status": {
            row["status"]: row["n"]
            for row in legacy_rows("SELECT status, COUNT(*) n FROM reviews GROUP BY status")
        },
    }


def next_review(status: str = "unreviewed", after: int = 0) -> dict:
    if status not in (STATUSES | {"all"}):
        raise ValueError("Invalid review status")

    queryset = Lexeme.objects.using(LEXICON)
    if status != "all":
        queryset = queryset.filter(human_status=status)
    total = queryset.count()
    entry = queryset.filter(id__gt=after).order_by("id").first()
    if entry is None:
        entry = queryset.order_by("id").first()
    if entry is None:
        return {"word": None, "total": total, "sources": []}

    return {
        "word": {
            "id": entry.id,
            "lemma": entry.lemma,
            "pos": entry.pos,
            "human_status": entry.human_status,
        },
        "total": total,
        "sources": detail(entry.id)["sources"],
    }
