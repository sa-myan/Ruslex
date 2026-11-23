"""Resumable enrichment and isolated candidate database assembly."""
import json
import sqlite3
import tempfile
from pathlib import Path
from .prompts import BASE_PROMPT, LEXEME_TASK, PAGE_TASK
from .provider import opencode
from .storage import read_database, write_database, snapshot, atomic_json, checked_workspace, staged_files, inputs, chunks
from .validation import validate_lexemes, validate_pages, normalized
from .taxonomy import seed_tags

def validated_model_batch(response, *, stage: str, batch, prompt: str, model: str,
                          executable: str, timeout: int, workspace: Path, phase: str):
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
        verify_model: str | None = None):
    source = checked_workspace(workspace)
    with read_database(source) as db:
        todo = list(inputs(db, stage))
    expected = len(todo)
    completed = 0
    for batch in chunks(todo, batch_size):
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
        response = opencode(prompt, model, executable, timeout)
        validated = validated_model_batch(
            response, stage=stage, batch=batch, prompt=prompt, model=model,
            executable=executable, timeout=timeout, workspace=workspace,
            phase="generate")
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
            reviewed = opencode(verify_prompt, verify_model, executable, timeout)
            validated = validated_model_batch(
                reviewed, stage=stage, batch=batch, prompt=verify_prompt,
                model=verify_model, executable=executable, timeout=timeout,
                workspace=workspace, phase="verify")
            normalized_result = {"input_ids": ids,
                                 "entries" if stage == "lexemes" else "expressions": validated}
        atomic_json(target, normalized_result)
        completed += 1
        print(f"{stage}: saved {target.name}; {len(validated)} records", flush=True)
    remaining = sum(not (workspace / "batches" / stage /
                        f"{part[0]['id']:06d}-{part[-1]['id']:06d}.json").exists()
                    for part in chunks(todo, batch_size))
    return {"stage": stage, "total_inputs": expected, "new_batches": completed,
            "remaining_batches": remaining, "batch_size": batch_size}


def report(workspace: Path):
    source = checked_workspace(workspace)
    with read_database(source) as db:
        total = {"lexemes": len(list(inputs(db, "lexemes"))),
                 "pages": len(list(inputs(db, "pages")))}
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
    existing = db.execute("SELECT id FROM lexemes WHERE lemma=? AND pos=? AND entry_type='word'",
                          (lemma, pos)).fetchone()
    if existing:
        return existing[0]
    options = db.execute("SELECT id FROM lexemes WHERE lemma=? AND entry_type='word'", (lemma,)).fetchall()
    if len(options) == 1:
        return options[0][0]
    cursor = db.execute("INSERT INTO lexemes(lemma,pos,entry_type,human_status) VALUES(?,?,'word','followup')",
                        (lemma, pos))
    missing_words.add(f"{lemma}/{pos}")
    return cursor.lastrowid


def build(workspace: Path, output: Path, *, allow_partial=False):
    source = checked_workspace(workspace)
    if output.exists():
        raise FileExistsError("Output file already exists; choose another filename")
    entries = {}
    expressions = {}
    with read_database(source) as db:
        source_words = {row["id"]: dict(row) for row in db.execute(
            "SELECT id,lemma,pos FROM lexemes WHERE human_status='kept' AND entry_type='word'")}
        source_pages = {row["id"]: row["markdown"] for row in db.execute(
            "SELECT id,markdown FROM pages")}
        expected = {row[0] for row in db.execute(
            "SELECT id FROM lexemes WHERE human_status='kept' AND entry_type='word'")}
        expected_pages = {row[0] for row in db.execute("SELECT id FROM pages")}
    for file in staged_files(workspace, "lexemes"):
        data = json.loads(file.read_text(encoding="utf-8"))
        group = data.get("input_ids", [])
        if len(set(group)) != len(group) or any(i not in source_words for i in group):
            raise ValueError("Invalid staged word IDs")
        for item in validate_lexemes(data, {i: source_words[i] for i in group}):
            if item["id"] in entries:
                raise ValueError(f"Duplicate enriched lexeme ID: {item['id']}")
            entries[item["id"]] = item
    if not allow_partial and expected != set(entries):
        raise RuntimeError(f"Enrichment incomplete: {len(expected - set(entries))} kept lexemes missing. "
                           "Run remaining batches or explicitly use --allow-partial for a preview")
    covered_pages = set()
    for file in staged_files(workspace, "pages"):
        staged = json.loads(file.read_text(encoding="utf-8"))
        group = staged.get("input_ids", [])
        if len(set(group)) != len(group) or any(i not in source_pages for i in group):
            raise ValueError("Invalid staged page IDs")
        if covered_pages & set(group):
            raise ValueError("Page was processed in overlapping batches")
        validate_pages(staged, {i: source_pages[i] for i in group})
        covered_pages.update(group)
    if not allow_partial and expected_pages != covered_pages:
        raise RuntimeError(f"Expression mining incomplete: {len(expected_pages - covered_pages)} "
                           "source pages unprocessed")
    for file in staged_files(workspace, "pages"):
        for expr in json.loads(file.read_text(encoding="utf-8"))["expressions"]:
            key = (expr["lemma"].lower(), expr["pos"])
            if key not in expressions:
                expressions[key] = expr
            else:
                seen = {(a["page_id"], a["surface"]) for a in expressions[key]["attestations"]}
                expressions[key]["attestations"].extend(
                    a for a in expr["attestations"] if (a["page_id"], a["surface"]) not in seen)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".enriched-", suffix=".db", dir=output.parent,
                                     delete=False) as temp:
        working = Path(temp.name)
    missing_words = set()
    unresolved_relations = []
    try:
        snapshot(source, working)
        with write_database(working) as db:
            db.execute("BEGIN IMMEDIATE")
            # Do NOT touch book/page/review/source tables, personal notes,
            # external links, lexeme IDs, or original kept/hidden decisions.
            for name in ("sense_tags", "patterns", "examples", "lexeme_relations",
                         "expression_components", "senses", "tags"):
                db.execute("DELETE FROM " + name)
            db.execute("UPDATE lexemes SET aspect=NULL,animacy=NULL WHERE entry_type='word'")
            seed_tags(db)
            sense_ids = {}
            for entry_id, item in sorted(entries.items()):
                db.execute("UPDATE lexemes SET aspect=?,animacy=? WHERE id=? AND entry_type='word'",
                           (item["aspect"], item["animacy"], entry_id))
                sense_ids[entry_id] = insert_senses(db, entry_id, item["senses"])
            created_expressions = 0
            for (lemma, pos), expr in sorted(expressions.items()):
                row = db.execute("SELECT id,entry_type FROM lexemes WHERE lemma=? AND pos=?",
                                 (lemma, pos)).fetchone()
                if row and row["entry_type"] != "expression":
                    raise ValueError(f"Expression conflicts with word entry: {lemma}/{pos}")
                if row:
                    expression_id = row["id"]
                else:
                    expression_id = db.execute("""INSERT INTO lexemes
                        (lemma,pos,entry_type,human_status) VALUES(?,?,'expression','kept')""",
                        (lemma, pos)).lastrowid
                    created_expressions += 1
                insert_senses(db, expression_id, expr["senses"])
                for position, comp in enumerate(expr["components"], start=1):
                    word_id = find_or_add_word(db, comp["lemma"], comp["pos"], missing_words)
                    db.execute("""INSERT INTO expression_components
                        (expression_id,word_id,position,surface) VALUES(?,?,?,?)""",
                        (expression_id, word_id, position, comp["surface"]))
                for att in expr["attestations"]:
                    page = db.execute("SELECT markdown FROM pages WHERE id=?", (att["page_id"],)).fetchone()
                    if page is None or normalized(att["surface"]) not in normalized(page[0]):
                        raise RuntimeError("Attestation changed since validation")
                    db.execute("""INSERT OR IGNORE INTO lexeme_pages
                        (lexeme_id,page_id,surface,context,count) VALUES(?,?,?,?,1)""",
                        (expression_id, att["page_id"], att["surface"], att["surface"]))
            existing = {(row["lemma"], row["pos"]): (row["id"], row["aspect"])
                        for row in db.execute("SELECT id,lemma,pos,aspect FROM lexemes")}
            for source_id, item in entries.items():
                for relation in item.get("relations", []):
                    target_key = (relation["target_lemma"].strip().lower(), relation["target_pos"])
                    target = existing.get(target_key)
                    if not target:
                        unresolved_relations.append({"source_id": source_id, **relation})
                        continue
                    target_id, target_aspect = target
                    if source_id == target_id:
                        continue
                    if relation["type"] == "aspect_pair" and \
                            {item["aspect"], target_aspect} != {"imperfective", "perfective"}:
                        unresolved_relations.append({"source_id": source_id, **relation})
                        continue
                    first, second = sorted((source_id, target_id)) if relation["type"] in \
                        {"aspect_pair", "synonym", "antonym", "related"} else (source_id, target_id)
                    source_sense = None
                    if relation.get("source_sense_index") is not None:
                        source_sense = sense_ids[source_id][relation["source_sense_index"]]
                    db.execute("""INSERT OR IGNORE INTO lexeme_relations
                        (source_lexeme_id,target_lexeme_id,relation_type,source_sense_id)
                        VALUES(?,?,?,?)""", (first, second, relation["type"],
                                               source_sense if first == source_id else None))
            issues = db.execute("PRAGMA foreign_key_check").fetchall()
            if issues:
                raise RuntimeError(f"Foreign key violations: {issues[:5]}")
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Built database failed SQLite integrity_check")
        working.replace(output)
    finally:
        if working.exists():
            working.unlink()
    result = {"database": str(output), "enriched_lexemes": len(entries),
              "new_expressions": created_expressions,
              "unresolved_relations": unresolved_relations,
              "new_component_words_needing_enrichment": sorted(missing_words)}
    atomic_json(output.with_suffix(".report.json"), result)
    return {"database": str(output), "enriched_lexemes": len(entries),
            "new_expressions": created_expressions,
            "unresolved_relation_count": len(unresolved_relations),
            "component_words_for_followup": len(missing_words)}

