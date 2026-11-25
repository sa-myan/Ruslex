"""On-demand VPS processing: OCR → AI review → optional enrichment → promotion.

All commands operate on candidate databases in /work, except 'plan' which
reads the live database and 'promote' which performs a guarded append-only
transaction. The public website never calls this module.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

from .audit import connect_read_only, make_audit
from .book_status import status as book_status
from .abbreviations import (
    plan as abbreviation_plan, rehearse as abbreviation_rehearse,
    initialize as abbreviation_init, categorize as abbreviation_categorize,
)
from .paradigms import (initialize as forms_initialize, plan as forms_plan,
                        backfill as forms_backfill, rehearse as forms_rehearse)
from .enrichment_merge import apply_enrichment
from .forms import resolve, review_batch, apply_decisions
from .openrussian import connect_reference, lookup, result as reference_result, verify_schema, reference_fingerprint
from .reference_audit import audit_entries, write_report, suggested_report_path
from .stress_diagnostics import diagnose as diagnose_stress
from .stress_ai import analyze as stress_ai_analyze, plan as stress_ai_plan, apply as stress_ai_apply, parse_approval_ids, preview_approvals as stress_ai_approval_preview
from .pronunciations import initialize as stress_initialize, backfill_plan as stress_plan, apply_backfill as stress_apply, rehearse as stress_rehearse
from .ocr import import_book, inspect
from .promotion import create_workspace, plan, promote, workspace_paths
from .storage import atomic_json, inventory, prepare, read_database, write_database
from .workflow import report, run

LIVE_DB = Path("/live/lexicon.db")
WORK_ROOT = Path("/work")
OCR_ROOT = Path("/ocr")
BACKUP_ROOT = Path("/backups")
REFERENCE_DB = Path("/reference/openrussian.db")


def workspace_dir(name: str) -> Path:
    if not name or name in {".", ".."} or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in name):
        raise ValueError("Workspace name must contain only letters, numbers, underscore or hyphen")
    return WORK_ROOT / name


def add_workspace(command):
    command.add_argument("name", help="Workspace identifier, e.g. russian_book_2")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("inventory", help="Read-only statistics on the live dictionary")
    reference = commands.add_parser("reference", help="Explore the read-only OpenRussian database")
    reference_commands = reference.add_subparsers(dest="reference_command", required=True)
    reference_commands.add_parser("info", help="Inspect source schema and record counts")
    ref_lookup = reference_commands.add_parser("lookup", help="Find headword readings and translations")
    ref_lookup.add_argument("lemma", help="One Russian dictionary headword")
    ref_lookup.add_argument("--forms", action="store_true", help="Include inflected forms as reference data")
    reference_commands.add_parser("audit", help="Export stress/ё candidates for Ruslex lexemes")
    stress = commands.add_parser("stress", help="Pronunciation migration and read-only plan")
    stress_actions = stress.add_subparsers(dest="stress_action", required=True)
    stress_actions.add_parser("plan", help="Show safe candidates; no writes")
    stress_actions.add_parser("diagnose", help="Explain remaining headwords; report only")
    stress_actions.add_parser("rehearse", help="Test migration/backfill against an isolated snapshot")
    ai_run = stress_actions.add_parser("ai-run", help="Resumable AI pronunciation exceptions; stages only")
    ai_run.add_argument("name")
    ai_run.add_argument("--model", required=True)
    ai_run.add_argument("--book", help="Only unresolved headwords attested in this imported book")
    ai_run.add_argument("--verify-model")
    ai_run.add_argument("--batch-size", type=int, default=8)
    ai_run.add_argument("--max-batches", type=int)
    ai_run.add_argument("--timeout", type=int, default=240)
    ai_run.add_argument("--dry-run", action="store_true")
    ai_plan = stress_actions.add_parser("ai-plan", help="Review staged AI decisions; read-only")
    ai_plan.add_argument("name")
    ai_review = stress_actions.add_parser("ai-approval-plan", help="Read-only preview of a selected pronunciation approval set")
    ai_review.add_argument("name")
    ai_review.add_argument("--approve", required=True, help="Comma-separated IDs reviewed by the operator")
    ai_apply = stress_actions.add_parser("ai-apply", help="Apply verified choices or explicitly approved IDs, after backup")
    ai_apply.add_argument("name")
    ai_apply.add_argument("--confirm", action="store_true", required=True)
    ai_apply.add_argument("--approve", help="Comma-separated lexeme IDs explicitly approved by a human")
    for action in ("init", "backfill"):
        step = stress_actions.add_parser(action)
        step.add_argument("--confirm", action="store_true", required=True)
    abbr = commands.add_parser("abbreviations", help="Classify lexical abbreviations")
    abbr_actions = abbr.add_subparsers(dest="abbr_action", required=True)
    abbr_actions.add_parser("plan", help="Show known candidates and uncertain definitions")
    abbr_actions.add_parser("rehearse", help="Test the safe schema migration on a snapshot")
    for action in ("init", "categorize"):
        abbr_actions.add_parser(action).add_argument("--confirm", action="store_true", required=True)
    form_cmd = commands.add_parser("forms", help="Russian inflection paradigms")
    form_steps = form_cmd.add_subparsers(dest="forms_action", required=True)
    form_steps.add_parser("plan", help="Read-only headword form generation preview")
    form_steps.add_parser("rehearse", help="Generate on a disposable DB copy")
    for step in ("init", "backfill"):
        item = form_steps.add_parser(step)
        item.add_argument("--confirm", action="store_true", required=True)
    audit_cmd = commands.add_parser("audit", help="Read-only audit of live or staged dictionary")
    audit_cmd.add_argument("--workspace", help="Optional candidate workspace name")
    audit_cmd.add_argument("--sample-size", type=int, default=150)
    create = commands.add_parser("workspace", help="Create isolated baseline and candidate from live")
    add_workspace(create)
    book_progress = commands.add_parser("book-status", help="Summarize an OCR book workspace and what remains")
    add_workspace(book_progress)
    book_progress.add_argument("--book", required=True)
    inspect_command = commands.add_parser("inspect-ocr", help="Preview Mistral OCR export without importing")
    inspect_command.add_argument("input", type=Path, help="Source file or directory inside /ocr")

    book_init = commands.add_parser("book-start", help="Create workspace and import OCR in one step")
    add_workspace(book_init)
    book_init.add_argument("--input", type=Path, required=True)
    book_init.add_argument("--book", required=True)
    book_init.add_argument("--edition", default="")
    book_init.add_argument("--first", type=int, help="Defaults to first page detected in OCR")
    book_init.add_argument("--last", type=int, help="Defaults to last page detected in OCR")
    book_init.add_argument("--offset", type=int, default=0)
    book_init.add_argument("--page-shift", type=int, default=0)
    book_run = commands.add_parser("book-run", help="Resume OCR AI resolution and enrichment")
    add_workspace(book_run)
    book_run.add_argument("--book", help="Defaults to title recorded at book-start")
    book_run.add_argument("--model", help="Required on first run, then remembered")
    book_run.add_argument("--verify-model")
    book_run.add_argument("--expressions", action="store_true", help="Also analyze pages for expressions")
    book_run.add_argument("--max-batches", type=int)
    book_run.add_argument("--dry-run", action="store_true")
    book_run.add_argument("--timeout", type=int, default=300)
    book_promote = commands.add_parser("book-promote", help="One final safe book promotion")
    add_workspace(book_promote)
    book_promote.add_argument("--confirm", action="store_true", required=True)

    importing = commands.add_parser("import-ocr", help="Import OCR into candidate; never writes live")
    add_workspace(importing)
    importing.add_argument("--input", type=Path, required=True)
    importing.add_argument("--book", required=True)
    importing.add_argument("--edition", default="")
    importing.add_argument("--first", required=True, type=int)
    importing.add_argument("--last", required=True, type=int)
    importing.add_argument("--offset", type=int, default=0)
    importing.add_argument("--page-shift", type=int, default=0)

    forms = commands.add_parser("resolve", help="Classify OCR forms with the configured LLM")
    add_workspace(forms)
    forms.add_argument("--book", required=True, help="Exact book title; avoids touching other books")
    forms.add_argument("--model", required=True)
    forms.add_argument("--batch-size", type=int, default=24)
    forms.add_argument("--max-batches", type=int)
    forms.add_argument("--timeout", type=int, default=240)
    forms.add_argument("--retry", action="store_true")
    forms.add_argument("--dry-run", action="store_true")

    review_list = commands.add_parser("review-forms", help="List pending or uncertain OCR forms in candidate")
    add_workspace(review_list)
    review_list.add_argument("--book", required=True)
    review_list.add_argument("--retry", action="store_true", help="Show uncertain rather than pending forms")
    review_list.add_argument("--limit", type=int, default=30)

    manual = commands.add_parser("decide-form", help="Manually accept/exclude a candidate OCR form")
    add_workspace(manual)
    manual.add_argument("--book", required=True)
    manual.add_argument("--id", required=True, type=int)
    manual.add_argument("--decision", required=True, choices=("admit", "exclude", "review"))
    manual.add_argument("--lemma", help="Required with admit; must be a known morphological option")
    manual.add_argument("--pos", help="Required with admit")

    enrich_prepare = commands.add_parser("enrich-prepare", help="Snapshot candidate for resumable AI enrichment")
    add_workspace(enrich_prepare)
    enrich = commands.add_parser("enrich-run", help="Generate validated enrichment batches")
    add_workspace(enrich)
    enrich.add_argument("--stage", choices=("lexemes", "pages"), required=True)
    enrich.add_argument("--book", help="Process only this textbook (recommended)")
    enrich.add_argument("--model", required=True)
    enrich.add_argument("--batch-size", type=int)
    enrich.add_argument("--max-batches", type=int)
    enrich.add_argument("--timeout", type=int, default=300)
    enrich.add_argument("--verify-model")
    enrich.add_argument("--dry-run", action="store_true")
    enrich_status = commands.add_parser("enrich-report", help="Show enrichment progress")
    add_workspace(enrich_status)
    enrich_status.add_argument("--book", help="Same scope as enrichment runs")
    enrich_apply = commands.add_parser("enrich-apply", help="Add only missing senses and expressions to candidate")
    add_workspace(enrich_apply)
    planning = commands.add_parser("plan", help="Compare candidate to live; rejects existing-record changes")
    add_workspace(planning)
    promotion = commands.add_parser("promote", help="Backup then transactionally append new rows to live")
    add_workspace(promotion)
    promotion.add_argument("--confirm", action="store_true", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "abbreviations":
            if args.abbr_action == "plan":
                result = abbreviation_plan(LIVE_DB)
            elif args.abbr_action == "rehearse":
                result = abbreviation_rehearse(LIVE_DB, WORK_ROOT)
            elif args.abbr_action == "init":
                result = abbreviation_init(LIVE_DB, BACKUP_ROOT)
            else:
                result = abbreviation_categorize(LIVE_DB, BACKUP_ROOT)
        elif args.command == "forms":
            if args.forms_action == "plan":
                result = forms_plan(LIVE_DB)
            elif args.forms_action == "rehearse":
                result = forms_rehearse(LIVE_DB, WORK_ROOT)
            elif args.forms_action == "init":
                result = forms_initialize(LIVE_DB, BACKUP_ROOT)
            else:
                result = forms_backfill(LIVE_DB, BACKUP_ROOT)
        elif args.command == "stress":
            if args.stress_action == "plan":
                result = stress_plan(LIVE_DB, REFERENCE_DB)
            elif args.stress_action == "diagnose":
                result = diagnose_stress(LIVE_DB, REFERENCE_DB, WORK_ROOT)
            elif args.stress_action == "ai-run":
                result = stress_ai_analyze(
                    LIVE_DB, REFERENCE_DB, WORK_ROOT, name=args.name,
                    model=args.model, verify_model=args.verify_model,
                    batch_size=args.batch_size, max_batches=args.max_batches,
                    timeout=args.timeout, dry_run=args.dry_run,
                    book=args.book)
            elif args.stress_action == "ai-plan":
                result = stress_ai_plan(LIVE_DB, REFERENCE_DB, WORK_ROOT, args.name)
            elif args.stress_action == "ai-approval-plan":
                result = stress_ai_approval_preview(
                    LIVE_DB, REFERENCE_DB, WORK_ROOT,
                    args.name, parse_approval_ids(args.approve))
            elif args.stress_action == "ai-apply":
                result = stress_ai_apply(LIVE_DB, REFERENCE_DB, WORK_ROOT,
                                         BACKUP_ROOT, args.name, approved_ids=parse_approval_ids(args.approve))
            elif args.stress_action == "rehearse":
                result = stress_rehearse(LIVE_DB, REFERENCE_DB, WORK_ROOT)
            elif args.stress_action == "init":
                result = stress_initialize(LIVE_DB, BACKUP_ROOT)
            else:
                result = stress_apply(LIVE_DB, REFERENCE_DB, BACKUP_ROOT)
        elif args.command == "reference":
            with connect_reference(REFERENCE_DB) as dictionary:
                if args.reference_command == "info":
                    enabled = verify_schema(dictionary)
                    result = {
                        "reference_file": str(REFERENCE_DB),
                        "headwords": dictionary.execute("SELECT COUNT(*) FROM words").fetchone()[0],
                        "reference_sha256": reference_fingerprint(REFERENCE_DB),
                        "available_tables": enabled,
                        "optional_record_counts": {
                            table: dictionary.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                            for table, present in enabled.items() if present
                        },
                        "source": "OpenRussian (user-provided reference dump)",
                        "data_mutation": "none",
                    }
                elif args.reference_command == "lookup":
                    matches = lookup(dictionary, args.lemma)
                    result = {
                        "query": args.lemma,
                        "matches": [reference_result(word, dictionary, include_forms=args.forms) for word in matches],
                        "count": len(matches),
                        "warning": "Reference readings are candidates, not verified Ruslex pronunciations.",
                    }
                elif args.reference_command == "audit":
                    with read_database(LIVE_DB) as lexicon:
                        rows = audit_entries(dictionary, lexicon)
                    result = write_report(rows, suggested_report_path(WORK_ROOT))
                    result["reference_sha256"] = reference_fingerprint(REFERENCE_DB)
                    atomic_json(Path(result["csv"]).parent / "summary.json", result)
                else:
                    parser.error("Unknown reference subcommand")
        elif args.command == "inventory":
            result = inventory(LIVE_DB)
        elif args.command == "audit":
            if not 0 <= args.sample_size <= 1000:
                raise ValueError("--sample-size must be between 0 and 1000")
            source = LIVE_DB
            output_root = WORK_ROOT / "audits"
            if args.workspace:
                staging = workspace_dir(args.workspace)
                _, source = workspace_paths(staging)
                output_root = staging / "audits"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            directory = output_root / stamp
            with closing(connect_read_only(source)) as db:
                result = make_audit(db, directory, args.sample_size, seed=20261122)
            result = {"report": str(directory / "audit_summary.md"), **result}
        elif args.command == "book-start":
            from .book_pipeline import start
            source = args.input.resolve()
            if not source.is_relative_to(OCR_ROOT):
                raise ValueError("OCR input must be under /ocr")
            result = start(
                LIVE_DB, workspace_dir(args.name), source,
                book=args.book, edition=args.edition, first=args.first,
                last=args.last, offset=args.offset, page_shift=args.page_shift,
            )
        elif args.command == "book-promote":
            from .book_pipeline import finalize
            result = finalize(LIVE_DB, workspace_dir(args.name), BACKUP_ROOT,
                              confirmed=args.confirm)
        elif args.command == "inspect-ocr":
            source = args.input.resolve()
            if not source.is_relative_to(OCR_ROOT):
                raise ValueError("OCR input must be under /ocr, mounted read-only")
            result = inspect(source)
        else:
            workspace = workspace_dir(args.name)
            if args.command == "workspace":
                result = create_workspace(LIVE_DB, workspace)
            else:
                _, candidate = workspace_paths(workspace)
                if args.command == "book-run":
                    from .book_pipeline import advance
                    result = advance(
                        LIVE_DB, workspace, book=args.book, model=args.model,
                        verify_model=args.verify_model, expressions=args.expressions,
                        max_batches=args.max_batches, timeout=args.timeout,
                        dry_run=args.dry_run,
                    )
                elif args.command == "book-status":
                    result = book_status(workspace, args.book)
                elif args.command == "import-ocr":
                    source = args.input.resolve()
                    if not source.is_relative_to(OCR_ROOT):
                        raise ValueError("OCR input must be under /ocr")
                    with write_database(candidate) as db:
                        result = import_book(
                            db, title=args.book.strip(), edition=args.edition.strip(),
                            source=source, first=args.first, last=args.last,
                            offset=args.offset, page_shift=args.page_shift,
                        )
                elif args.command == "resolve":
                    with write_database(candidate) as db:
                        result = resolve(
                            db, workspace=workspace, book=args.book, model=args.model,
                            batch_size=args.batch_size, max_batches=args.max_batches,
                            timeout=args.timeout, retry=args.retry, dry_run=args.dry_run,
                        )
                elif args.command == "review-forms":
                    if not 1 <= args.limit <= 100:
                        raise ValueError("--limit must be 1-100")
                    with read_database(candidate) as db:
                        result = {"forms": review_batch(db, args.book, args.limit, retry=args.retry)}
                elif args.command == "decide-form":
                    with write_database(candidate) as db:
                        matches = review_batch(db, args.book, 100000, retry=False) + review_batch(
                            db, args.book, 100000, retry=True)
                        matching = [item for item in matches if item["id"] == args.id]
                        if not matching:
                            raise ValueError("Form ID not in this book's pending/review queue")
                        entries = [{"lemma": args.lemma, "pos": args.pos}] if args.decision == "admit" else []
                        if args.decision == "admit" and (not args.lemma or not args.pos):
                            raise ValueError("Admit requires --lemma and --pos")
                        result = apply_decisions(db, matching, {"results": [{
                            "id": args.id, "decision": args.decision, "confidence": "high",
                            "entries": entries, "reason": "Manually reviewed on VPS",
                        }]}, "manual")
                elif args.command == "enrich-prepare":
                    result = prepare(candidate, workspace / "enrichment")
                elif args.command == "enrich-run":
                    result = run(
                        workspace / "enrichment", stage=args.stage, model=args.model,
                        executable="opencode", batch_size=args.batch_size or (4 if args.stage == "lexemes" else 2),
                        max_batches=args.max_batches, timeout=args.timeout,
                        dry_run=args.dry_run, verify_model=args.verify_model, book=args.book,
                    )
                elif args.command == "enrich-report":
                    result = report(workspace / "enrichment", book=args.book)
                elif args.command == "enrich-apply":
                    result = apply_enrichment(workspace)
                elif args.command == "plan":
                    result = plan(LIVE_DB, workspace)
                elif args.command == "promote":
                    result = promote(LIVE_DB, workspace, BACKUP_ROOT, confirmed=args.confirm)
                else:
                    parser.error("Unknown command")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, RuntimeError, FileNotFoundError, FileExistsError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
