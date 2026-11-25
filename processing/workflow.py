"""Resumable AI analysis and validated staging (no replacement build)."""
import json
import sqlite3
import tempfile
from pathlib import Path
from .prompts import BASE_PROMPT, LEXEME_TASK, PAGE_TASK
from .provider import opencode
from .progress import AIProgress
from .storage import read_database, write_database, snapshot, atomic_json, checked_workspace, staged_files, inputs, chunks, new_word_ids
from .validation import validate_lexemes, validate_pages, normalized
from .taxonomy import seed_tags

def validated_model_batch(response, *, stage: str, batch, prompt: str, model: str,
                          executable: str, timeout: int, workspace: Path, phase: str,
                          progress: AIProgress | None = None):
    """Validate model output; request at most two targeted repairs when needed.

    Rejected responses are kept for inspection but are never imported.
    """
    ids = [item["id"] for item in batch]
    first, last = ids[0], ids[-1]
    for attempt in range(3):
        try:
            if stage == "lexemes":
                return validate_lexemes(response, {item["id"]: item for item in batch})
            return validate_pages(response, {item["id"]: item["markdown"] for item in batch})
        except (ValueError, TypeError, KeyError) as exc:
            rejected = (workspace / "rejected" / stage /
                        f"{first:06d}-{last:06d}-{phase}-attempt{attempt + 1}.json")
            atomic_json(rejected, {"validation_error": str(exc), "response": response})
            if attempt == 2:
                raise ValueError(
                    f"{stage} batch {first}-{last} failed validation after 3 responses: "
                    f"{exc}. Rejected output saved in {rejected}"
                ) from exc
            if progress:
                progress.retry(first_id=first, last_id=last,
                               attempt=attempt + 1, error=str(exc), phase=phase)
            else:
                print(f"{stage} batch {first}-{last}: {exc}; "
                      f"requesting correction {attempt + 1}/2", flush=True)
            repair_prompt = (BASE_PROMPT + "\n\nVALIDATION REPAIR: The following output failed "
                "a strict database validation check. Correct the error, preserving "
                "all other sound linguistic content. Return the COMPLETE corrected "
                "JSON structure, including exactly the original input IDs and fields. "
                "Do not add comments, Markdown, or extra entries. If an English "
                "meaning includes Russian text, translate it; an English description "
                "may quote Russian terms inside English prose. Preserve genuine "
                "Russian examples and grammatical patterns. "
                f"\nERROR: {exc}\nORIGINAL TASK:\n{prompt}\nREJECTED JSON:\n" +
                json.dumps(response, ensure_ascii=False))
            response = opencode(repair_prompt, model, executable, timeout)
    raise AssertionError("Unreachable")


def run(workspace: Path, *, stage: str, model: str, executable: str,
        batch_size: int, max_batches: int | None, timeout: int, dry_run=False,
        verify_model: str | None = None, book: str | None = None):
    source = checked_workspace(workspace)
    selection = workspace / f"selection-{stage}.json"
    previous = json.loads(selection.read_text(encoding="utf-8")) if selection.exists() else None
    if previous is not None and previous != {"book": book}:
        raise RuntimeError("Enrichment scope changed; start a new workspace")
    if previous is None and not dry_run:
        atomic_json(selection, {"book": book})
    with read_database(source) as db:
        todo = list(inputs(db, stage, book=book,
                           allow_new_ids=new_word_ids(workspace)))
    expected = len(todo)
    completed = 0
    all_batches = list(chunks(todo, batch_size))
    prior = sum(len(batch) for batch in all_batches
                if (workspace / "batches" / stage /
                    f"{batch[0]['id']:06d}-{batch[-1]['id']:06d}.json").exists())
    progress = AIProgress(stage, total=expected, completed=prior,
                          batch_size=batch_size, max_batches=max_batches)
    if not dry_run:
        progress.begin()
    for batch_number, batch in enumerate(all_batches, start=1):
        ids = [item["id"] for item in batch]
        target = workspace / "batches" / stage / f"{ids[0]:06d}-{ids[-1]:06d}.json"
        if target.exists():
            continue
        if max_batches is not None and completed >= max_batches:
            break
        payload = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
        prompt = BASE_PROMPT + "\n\n" + (LEXEME_TASK if stage == "lexemes" else PAGE_TASK) + payload
        if dry_run:
            print(json.dumps({"stage": stage, "first_ids": ids,
                              "model": model, "prompt_preview": prompt[:2000]},
                             ensure_ascii=False, indent=2))
            break
        progress.batch_start(number=batch_number, first_id=ids[0],
                             last_id=ids[-1], count=len(ids))
        try:
            response = opencode(prompt, model, executable, timeout)
            validated = validated_model_batch(
                response, stage=stage, batch=batch, prompt=prompt, model=model,
                executable=executable, timeout=timeout, workspace=workspace,
                phase="generate", progress=progress)
        except Exception as exc:
            progress.failure(exc)
            raise
        normalized_result = {"input_ids": ids,
                             "entries" if stage == "lexemes" else "expressions": validated}
        if verify_model:
            verify_prompt = (BASE_PROMPT + "\n\nIndependently scrutinize this prior analysis "
                "for false lexical senses, case government errors, false aspect pairs, "
                "unnatural examples, unsupported multiword expressions and weak tags. "
                "Correct every real error. Return EXACTLY the same JSON structure, "
                "including all requested IDs and actual page attestations. "
                "ORIGINAL SOURCE INPUT:\n" + payload + "\nPRIOR OUTPUT:\n" +
                json.dumps(normalized_result, ensure_ascii=False))
            try:
                reviewed = opencode(verify_prompt, verify_model, executable, timeout)
                validated = validated_model_batch(
                    reviewed, stage=stage, batch=batch, prompt=verify_prompt,
                    model=verify_model, executable=executable, timeout=timeout,
                    workspace=workspace, phase="verify", progress=progress)
            except Exception as exc:
                progress.failure(exc)
                raise
            normalized_result = {"input_ids": ids,
                                 "entries" if stage == "lexemes" else "expressions": validated}
        atomic_json(target, normalized_result)
        completed += 1
        progress.saved(len(ids), extra=f"{len(validated)} records; file {target.name}")
    if not dry_run:
        progress.finish()
    remaining = sum(not (workspace / "batches" / stage /
                        f"{part[0]['id']:06d}-{part[-1]['id']:06d}.json").exists()
                    for part in chunks(todo, batch_size))
    return {"stage": stage, "total_inputs": expected, "new_batches": completed,
            "remaining_batches": remaining, "batch_size": batch_size}


def report(workspace: Path, *, book: str | None = None):
    source = checked_workspace(workspace)
    with read_database(source) as db:
        total = {"lexemes": len(list(inputs(db, "lexemes", book=book,
                          allow_new_ids=new_word_ids(workspace)))),
                 "pages": len(list(inputs(db, "pages", book=book)))}
    complete = {}
    for stage in ("lexemes", "pages"):
        entries = 0
        for file in staged_files(workspace, stage):
            result = json.loads(file.read_text(encoding="utf-8"))
            entries += len(result.get("entries" if stage == "lexemes" else "expressions", []))
        complete[stage] = {"input_total": total[stage], "batch_files": len(staged_files(workspace, stage)),
                           "records_staged": entries}
    return complete


def insert_senses(db, lexeme_id: int, senses):
    ids = []
    for sense in senses:
        cursor = db.execute("INSERT INTO senses(lexeme_id,meaning,description) VALUES(?,?,?)",
                            (lexeme_id, sense["meaning"].strip(), sense.get("description", "").strip()))
        sense_id = cursor.lastrowid
        ids.append(sense_id)
        for category, names in sense["tags"].items():
            for name in names:
                row = db.execute("SELECT id FROM tags WHERE category=? AND name=?",
                                 (category, name)).fetchone()
                if row is None:
                    raise RuntimeError(f"Missing tag seed: {category}/{name}")
                db.execute("INSERT OR IGNORE INTO sense_tags(sense_id,tag_id) VALUES(?,?)",
                           (sense_id, row[0]))
        for pattern in sense["patterns"]:
            db.execute("INSERT INTO patterns(sense_id,pattern) VALUES(?,?)", (sense_id, pattern.strip()))
        for example in sense["examples"]:
            db.execute("INSERT INTO examples(sense_id,russian,english) VALUES(?,?,?)",
                       (sense_id, example["russian"].strip(), example["english"].strip()))
    return ids


def find_or_add_word(db, lemma: str, pos: str, missing_words: set[str]):
    lemma = lemma.strip().lower()
    existing = db.execute("""SELECT id FROM lexemes WHERE lemma=? AND pos=?
                             AND entry_type IN ('word','abbreviation')""",
                          (lemma, pos)).fetchone()
    if existing:
        return existing[0]
    options = db.execute(
        "SELECT id FROM lexemes WHERE lemma=? AND entry_type IN ('word','abbreviation')",
        (lemma,),
    ).fetchall()
    if len(options) == 1:
        return options[0][0]
    cursor = db.execute("INSERT INTO lexemes(lemma,pos,entry_type,human_status) VALUES(?,?,'word','followup')",
                        (lemma, pos))
    missing_words.add(f"{lemma}/{pos}")
    return cursor.lastrowid


