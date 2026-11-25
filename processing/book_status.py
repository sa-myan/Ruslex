"""Concise read-only progress report for an isolated book-import workspace."""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from .promotion import workspace_paths
from .storage import read_database


def status(workspace: Path, book: str) -> dict:
    baseline, candidate = workspace_paths(workspace)
    with read_database(candidate) as db, read_database(baseline) as original:
        books = db.execute(
            "SELECT id,edition FROM books WHERE title=? ORDER BY id", (book,)
        ).fetchall()
        if len(books) != 1:
            raise ValueError(
                f"Expected exactly one edition for book {book!r}; found {len(books)}. "
                "Choose a distinct title for each edition."
            )
        book_id = books[0]["id"]
        pages = db.execute("SELECT COUNT(*) FROM pages WHERE book_id=?",
                           (book_id,)).fetchone()[0]
        statuses = dict(Counter({
            row["status"]: row["n"] for row in db.execute(
                "SELECT status,COUNT(*) n FROM reviews WHERE book_id=? GROUP BY status",
                (book_id,)
            )
        }))
        attested = db.execute(
            """SELECT COUNT(DISTINCT lp.lexeme_id)
               FROM lexeme_pages lp JOIN pages p ON p.id=lp.page_id
               WHERE p.book_id=?""", (book_id,)
        ).fetchone()[0]
        before_ids = {row[0] for row in original.execute("SELECT id FROM lexemes")}
        new_entries = [
            row for row in db.execute(
                "SELECT id,human_status,entry_type FROM lexemes WHERE entry_type IN ('word','abbreviation')"
            ) if row["id"] not in before_ids
        ]
        new_statuses = dict(Counter(row["human_status"] for row in new_entries))
        remaining = statuses.get("pending", 0)
        uncertain = statuses.get("needs_review", 0)
        if remaining:
            next_step = "resolve (AI form classification)"
        elif uncertain:
            next_step = "review-forms --retry (uncertain forms only); promotion can leave these unresolved"
        else:
            next_step = "plan, then guarded promote"
        return {
            "workspace": workspace.name, "book": book, "edition": books[0]["edition"],
            "pages_imported": pages, "review_decisions": statuses,
            "pending_forms": remaining, "uncertain_forms": uncertain,
            "distinct_attested_lexemes": attested,
            "new_word_entries": len(new_entries), "new_word_review_status": new_statuses,
            "new_entry_types": dict(Counter(row["entry_type"] for row in new_entries)),
            "ready_to_plan": remaining == 0,
            "next_step": next_step, "data_mutation": "none",
        }
