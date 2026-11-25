"""AI review of OCR surface forms in an isolated candidate database.

Adapted from Ruslex v3 legacy_cli/core.py and legacy_cli/ai.py.
Every complete AI batch is validated before changing its review decisions.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .ocr import normalize
from .provider import opencode
from .progress import AIProgress
from .storage import atomic_json

FORM_PROMPT = """You are a Russian lexicographer reviewing OCR of a textbook.
For each supplied surface form, choose a genuine Russian word interpretation
from the exact given morphological analyses, using the supplied contexts.
Reject OCR artifacts, broken fragments, and letter/phonetic demonstrations.
Classify genuine lexical abbreviations as entry_type="abbreviation" rather
than ordinary words. They can be inflecting (вуз) or initialisms (МГУ);
part of speech remains independent. All-caps headings alone do NOT prove an
abbreviation. Do not mark an unfamiliar capitalized OCR fragment as one
without contextual support. When uncertain, choose review.
Do not invent lemmas or context.
Return only JSON: {"results":[{"id":1,"decision":"admit|exclude|review",
"confidence":"high|medium|low","entries":[{"lemma":"...","pos":"...","entry_type":"word|abbreviation"}],
"reason":"brief"}]}. Return one result per input ID; no tools.
INPUT:
"""


def review_batch(db, book: str, limit: int = 24, retry: bool = False) -> list[dict]:
    editions = db.execute("SELECT COUNT(*) FROM books WHERE title=?", (book,)).fetchone()[0]
    if editions > 1:
        raise ValueError(
            f"Book title {book!r} matches multiple editions. "
            "Use a distinct title per imported edition until edition-scoped review is supported."
        )
    status = "needs_review" if retry else "pending"
    candidates = db.execute("""
        SELECT r.id,r.surface,r.analyses_json,r.book_id
        FROM reviews r JOIN books b ON b.id=r.book_id
        WHERE b.title=? AND r.status=? ORDER BY r.id LIMIT ?
    """, (book, status, limit)).fetchall()
    results = []
    for row in candidates:
        pages = db.execute("""
            SELECT p.pdf_page,p.printed_page,sp.context
            FROM surface_pages sp JOIN pages p ON p.id=sp.page_id
            WHERE p.book_id=? AND sp.surface=? ORDER BY p.pdf_page
        """, (row["book_id"], row["surface"])).fetchall()
        indices = {0, len(pages) // 2, len(pages) - 1}
        results.append({
            "id": row["id"], "surface": row["surface"],
            "analyses": json.loads(row["analyses_json"]),
            "examples": [{"pdf_page": pages[i]["pdf_page"],
                          "printed_page": pages[i]["printed_page"],
                          "context": pages[i]["context"][:190]}
                         for i in sorted(indices) if pages],
        })
    return results


def apply_decisions(db, batch: list[dict], response: dict, model: str) -> dict:
    """Reject any malformed/partial batch *before* beginning a transaction."""
    proposals = response.get("results") if isinstance(response, dict) else None
    if not isinstance(proposals, list) or len(proposals) != len(batch):
        raise ValueError("AI must return one decision for every input form")
    requested = {item["id"]: item for item in batch}
    seen = set()
    decisions = []
    for item in proposals:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise ValueError("Invalid AI form-review item")
        key = item["id"]
        if key not in requested or key in seen:
            raise ValueError("Unexpected or repeated review ID")
        seen.add(key)
        action = item.get("decision")
        if action not in {"admit", "exclude", "review"}:
            raise ValueError("Invalid review decision")
        confidence = item.get("confidence", "low")
        entries = []
        if action == "admit":
            allowed = {
                (part["lemma"], part["pos"], part.get("entry_type", "word"))
                for part in requested[key]["analyses"]
            }
            values = item.get("entries")
            if not isinstance(values, list) or not 1 <= len(values) <= 4:
                action = "review"
            else:
                for value in values:
                    if not isinstance(value, dict):
                        action = "review"
                        break
                    lemma = normalize(str(value.get("lemma", "")))
                    pos = str(value.get("pos", "")).upper()
                    entry_type = value.get("entry_type", "word")
                    pair = (lemma, pos, entry_type)
                    if pair not in allowed or pair in entries:
                        action = "review"
                        break
                    entries.append(pair)
            if confidence == "low":
                action = "review"
        decisions.append((key, action, str(item.get("reason", ""))[:1200],
                          entries if action == "admit" else []))
    counts = Counter()
    with db:
        for review_id, action, reason, entries in decisions:
            original = db.execute("SELECT book_id,surface,status FROM reviews WHERE id=?",
                                  (review_id,)).fetchone()
            if not original or original["status"] not in {"pending", "needs_review"}:
                raise RuntimeError("Review changed during AI request; batch cancelled")
            status = {"admit": "admitted", "exclude": "excluded",
                      "review": "needs_review"}[action]
            db.execute("""UPDATE reviews SET status=?,entries_json=?,reason=?,model=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, json.dumps(entries, ensure_ascii=False), reason, model, review_id))
            if status == "admitted":
                for lemma, pos, entry_type in entries:
                    # Existing lexemes, human decisions, senses and notes are preserved.
                    db.execute("""INSERT OR IGNORE INTO lexemes(lemma,pos,entry_type)
                                  VALUES (?,?,?)""", (lemma, pos, entry_type))
                    lexeme_id = db.execute("SELECT id FROM lexemes WHERE lemma=? AND pos=?",
                                           (lemma, pos)).fetchone()[0]
                    occurrences = db.execute("""
                        SELECT p.id,sp.count,sp.context FROM surface_pages sp
                        JOIN pages p ON p.id=sp.page_id
                        WHERE p.book_id=? AND sp.surface=?
                    """, (original["book_id"], original["surface"])).fetchall()
                    for page in occurrences:
                        db.execute("""INSERT OR IGNORE INTO lexeme_pages
                            (lexeme_id,page_id,surface,context,count) VALUES (?,?,?,?,?)""",
                            (lexeme_id, page["id"], original["surface"],
                             page["context"], page["count"]))
            counts[status] += 1
    return dict(counts)


def resolve(db, *, workspace: Path, book: str, model: str,
            executable: str = "opencode", batch_size: int = 24,
            max_batches: int | None = None, timeout: int = 240,
            retry: bool = False, dry_run: bool = False) -> dict:
    if not 1 <= batch_size <= 100:
        raise ValueError("batch-size must be between 1 and 100")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max-batches must be positive")
    if not db.execute("SELECT 1 FROM books WHERE title=?", (book,)).fetchone():
        raise ValueError("Book does not exist in candidate database")
    totals = Counter()
    completed = 0
    status = "needs_review" if retry else "pending"
    remaining_initial = db.execute(
        """SELECT COUNT(*) FROM reviews r JOIN books b ON b.id=r.book_id
           WHERE b.title=? AND r.status=?""", (book, status)
    ).fetchone()[0]
    # A resumed book run should show overall completion, rather than
    # resetting the progress bar to zero for each new CLI invocation.
    all_forms = db.execute(
        """SELECT COUNT(*) FROM reviews r JOIN books b ON b.id=r.book_id
           WHERE b.title=?""", (book,)
    ).fetchone()[0]
    total_for_pass = remaining_initial if retry else all_forms
    completed_before = 0 if retry else all_forms - remaining_initial
    progress = AIProgress(
        "forms" + ("/retry" if retry else ""),
        total=total_for_pass, completed=completed_before,
        batch_size=batch_size, max_batches=max_batches
    )
    if not dry_run:
        progress.begin()
    while max_batches is None or completed < max_batches:
        batch = review_batch(db, book, batch_size, retry=retry)
        if not batch:
            break
        while len(batch) > 1 and len(json.dumps(batch, ensure_ascii=False)) > 18000:
            batch = batch[:max(1, len(batch) // 2)]
        if dry_run:
            return {"dry_run": True, "next_batch": batch[:2], "total_pending":
                    db.execute("SELECT COUNT(*) FROM reviews WHERE status='pending' AND book_id "
                               "IN (SELECT id FROM books WHERE title=?)", (book,)).fetchone()[0]}
        prompt = FORM_PROMPT + json.dumps(batch, ensure_ascii=False)
        progress.batch_start(number=min(progress.total_batches, progress.completed // batch_size + 1),
                             first_id=batch[0]["id"],
                             last_id=batch[-1]["id"], count=len(batch))
        try:
            response = opencode(prompt, model, executable, timeout)
        except Exception as exc:
            progress.failure(exc)
            raise
        # Model outputs are retained as evidence; a failure never silently writes.
        start, end = batch[0]["id"], batch[-1]["id"]
        path = workspace / "form_reviews" / f"{start:06d}-{end:06d}.json"
        atomic_json(path, {"model": model, "input_ids": [b["id"] for b in batch],
                           "response": response})
        try:
            results = apply_decisions(db, batch, response, model)
        except Exception as exc:
            progress.failure(exc)
            raise
        totals.update(results)
        completed += 1
        progress.saved(len(batch), extra=f"decisions {dict(results)}")
        if retry:
            break  # Do not loop indefinitely over uncertain forms.
    if not dry_run:
        progress.finish()
    return {"batches": completed, "results": dict(totals)}
