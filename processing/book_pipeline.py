"""One-workspace book import: resumable AI, additive enrichment, one promotion.

The worker never writes live. This simply orchestrates tested building blocks,
retaining every existing audit, authorization and append-only promotion guard.
"""
from __future__ import annotations

import json
from pathlib import Path

from .book_status import status as book_status
from .enrichment_merge import apply_enrichment
from .forms import resolve
from .ocr import import_book, inspect
from .promotion import create_workspace, plan as promotion_plan, promote, workspace_paths
from .storage import atomic_json, prepare, read_database, write_database, staged_files, inputs, checked_workspace, new_word_ids
from .workflow import run as enrich_run

SETTINGS_FILE = "book-run-settings.json"


def start(live: Path, workspace: Path, source: Path, *,
          book: str, edition: str, first: int | None, last: int | None,
          offset: int = 0, page_shift: int = 0, analyzer=None) -> dict:
    """Create one isolated workspace and OCR-import the requested pages."""
    if not book.strip():
        raise ValueError("Book title cannot be empty")
    # Validate input before creating the persistent workspace.
    inspected = inspect(source)
    if inspected["pages"] < 1:
        raise ValueError("OCR has no pages")
    first = inspected["first_page"] if first is None else first
    last = inspected["last_page"] if last is None else last
    create_workspace(live, workspace)
    with write_database(workspace / "candidate.db") as db:
        imported = import_book(
            db, title=book, edition=edition, source=source,
            first=first, last=last, offset=offset, page_shift=page_shift,
            analyzer=analyzer,
        )
    atomic_json(workspace / "book-import.json", {
        "book": book, "edition": edition, "ocr_source": str(source),
        "first": first, "last": last, "offset": offset,
        "page_shift": page_shift,
    })
    return {"workspace": workspace.name, "ocr": imported,
            "status": book_status(workspace, book), "live_mutation": "none"}


def _settings(workspace: Path, *, book: str, model: str, verify_model: str | None,
              expressions: bool, dry_run: bool) -> dict:
    record = {"book": book, "model": model, "verify_model": verify_model,
              "expressions": expressions}
    file = workspace / SETTINGS_FILE
    if file.exists():
        if json.loads(file.read_text(encoding="utf-8")) != record:
            raise RuntimeError(
                "This workspace is already bound to other model/settings; "
                "resume with the same values"
            )
    elif not dry_run:
        atomic_json(file, record)
    return record


def _select_new_words(workspace: Path) -> list[int]:
    """New admitted words only, never existing hidden or manually curated data."""
    with read_database(workspace / "baseline.db") as base, read_database(workspace / "candidate.db") as candidate:
        old = {row[0] for row in base.execute("SELECT id FROM lexemes")}
        return [
            row[0] for row in candidate.execute(
                "SELECT id FROM lexemes WHERE entry_type='word' AND human_status!='hidden' ORDER BY id"
            ) if row[0] not in old
        ]


def advance(live: Path, workspace: Path, *, book: str | None = None,
            model: str | None = None,
            verify_model: str | None = None, expressions: bool = True,
            max_batches: int | None = None, timeout: int = 300,
            dry_run: bool = False, executable: str = "opencode") -> dict:
    """Advance to the next unfinished step; safe to repeat after interruptions."""
    existing = workspace / SETTINGS_FILE
    if existing.is_file():
        previous = json.loads(existing.read_text(encoding="utf-8"))
        book = book or previous["book"]
        model = model or previous["model"]
        verify_model = verify_model or previous["verify_model"]
        expressions = expressions or previous["expressions"]
    elif book is None:
        imported = workspace / "book-import.json"
        if imported.is_file():
            book = json.loads(imported.read_text(encoding="utf-8"))["book"]
    if not book:
        raise ValueError("No book title specified or recorded in workspace")
    if not model or not model.strip():
        raise ValueError("Model ID is required on the first book-run")
    if verify_model and verify_model == model:
        raise ValueError("Verifier must be a distinct model ID")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max-batches must be positive")
    workspace_paths(workspace)
    _settings(workspace, book=book, model=model, verify_model=verify_model,
              expressions=expressions, dry_run=dry_run)
    summary = book_status(workspace, book)
    if (workspace / "promotion.json").exists():
        raise RuntimeError("Workspace was already promoted; create a new workspace")

    forms_outcome = None
    if summary["pending_forms"]:
        with (read_database if dry_run else write_database)(workspace / "candidate.db") as db:
            forms_outcome = resolve(db, workspace=workspace, book=book, model=model,
                                    executable=executable, batch_size=24,
                                    max_batches=max_batches, timeout=timeout,
                                    dry_run=dry_run)
        summary = book_status(workspace, book)
        if dry_run or summary["pending_forms"]:
            return {"stage": "resolve_forms", "result": forms_outcome,
                    "status": summary, "next": "Run book-run again",
                    "live_mutation": "none"}
        # All mandatory OCR decisions are settled. Continue in this invocation
        # instead of forcing a second manual checkpoint.


    if dry_run:
        return {"stage": "enrichment", "status": summary,
                "preview": "No model calls or workspace writes in dry-run",
                "live_mutation": "none"}

    stage = workspace / "enrichment"
    if not (stage / "manifest.json").exists():
        # Freeze the new-word selection before enrichment's immutable snapshot.
        stage.mkdir(parents=True, exist_ok=True)
        atomic_json(stage / "new_lexemes.json", _select_new_words(workspace))
        prepared = prepare(workspace / "candidate.db", stage)
    else:
        prepared = None

    # The snapshot freezes exactly the book's admitted, retained lexemes and
    # pages before any model-dependent content is staged.
    for name, count in (("lexemes", 4), ("pages", 2)):
        if name == "pages" and not expressions:
            continue
        progress = enrich_run(
            stage, stage=name, model=model, executable=executable,
            batch_size=count, max_batches=max_batches, timeout=timeout,
            verify_model=verify_model, book=book,
        )
        if progress["remaining_batches"]:
            return {"stage": "enrich_" + name, "prepared": prepared,
                    "result": progress, "status": summary,
                    "next": "Run book-run again", "live_mutation": "none"}

    if not (workspace / "enrichment_review.json").is_file():
        any_staged = any(staged_files(stage, name) for name in ("lexemes", "pages"))
        if any_staged:
            applied = apply_enrichment(workspace)
        else:
            applied = {"nothing_to_enrich": True}
            atomic_json(workspace / "enrichment_review.json", {
                "statistics": applied, "unapplied_relationships": [],
                "component_words_for_followup": []
            })
    else:
        applied = {"already_applied": True}

    return {"stage": "ready_for_promotion", "form_review": forms_outcome,
            "enrichment": applied,
            "status": book_status(workspace, book),
            "plan": promotion_plan(live, workspace),
            "next": "Review plan, then run book-promote --confirm",
            "live_mutation": "none"}


def finalize(live: Path, workspace: Path, backups: Path, *, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("Explicit --confirm required")
    settings = workspace / SETTINGS_FILE
    if not settings.is_file():
        raise RuntimeError("Run book-run first")
    if not (workspace / "enrichment_review.json").is_file():
        # Valid for a textbook with no new senses/expressions only if all AI
        # enrichment inputs really had no work.
        from .storage import checked_workspace, inputs
        stage = workspace / "enrichment"
        source = checked_workspace(stage)
        config = json.loads(settings.read_text(encoding="utf-8"))
        with read_database(source) as db:
            expected = sum(1 for _ in inputs(
                db, "lexemes", book=config["book"],
                allow_new_ids=new_word_ids(stage)
            ))
            expected += (sum(1 for _ in inputs(db, "pages", book=config["book"]))
                         if config["expressions"] else 0)
        if expected:
            raise RuntimeError("Incomplete enrichment; finish book-run")
    result = promote(live, workspace, backups, confirmed=True)
    return {**result, "book_pipeline": True}
