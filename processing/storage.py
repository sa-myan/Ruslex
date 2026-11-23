"""SQLite snapshots, stage files, and immutable source manifest."""
import hashlib
import json
import re
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from .taxonomy import seed_tags, TAXONOMY_VERSION
from .validation import normalized

@contextmanager
def read_database(path: Path):
    if not path.is_file():
        raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


@contextmanager
def write_database(path: Path):
    db = sqlite3.connect(f"file:{path.resolve()}?mode=rw", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def snapshot(src: Path, dest: Path):
    with read_database(src) as original:
        with closing(sqlite3.connect(dest)) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite backup integrity check failed")


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".stage-", delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def sources_for_lexeme(db, lexeme_id: int):
    rows = db.execute("""SELECT lp.page_id,lp.context,lp.count,p.markdown
        FROM lexeme_pages lp JOIN pages p ON p.id=lp.page_id
        WHERE lp.lexeme_id=? ORDER BY lp.count DESC,lp.page_id LIMIT 15""",
        (lexeme_id,)).fetchall()
    selected = []
    for row in rows:
        raw = row["context"]
        snippet = normalized(raw) if raw else ""
        if len(snippet) < 15 or len(re.findall(r"[А-Яа-яЁё]+", raw)) < 3:
            continue
        if len(selected) >= 3:
            break
        selected.append({"page_id": row["page_id"], "text": re.sub(r"\s+", " ", raw)[:280]})
    return selected


def inputs(db, stage: str, *, book: str | None = None):
    """Return only un-enriched kept words, or attested pages, optionally per book.

    The book filter prevents a second book from rerunning thousands of already
    enriched entries. Existing manually maintained senses remain authoritative.
    """
    if book and db.execute(
        "SELECT COUNT(*) FROM books WHERE title=?", (book,)
    ).fetchone()[0] > 1:
        raise ValueError(
            f"Book title {book!r} matches multiple editions. "
            "Use a distinct title per imported edition until edition-scoped selection is supported."
        )
    if stage == "lexemes":
        sql = """SELECT l.id,l.lemma,l.pos FROM lexemes l
            WHERE l.entry_type='word' AND l.human_status='kept'
            AND NOT EXISTS (SELECT 1 FROM senses s WHERE s.lexeme_id=l.id)
        """
        values = []
        if book:
            sql += """AND EXISTS (SELECT 1 FROM lexeme_pages lp
                JOIN pages p ON p.id=lp.page_id
                JOIN books b ON b.id=p.book_id
                WHERE lp.lexeme_id=l.id AND b.title=?) """
            values.append(book)
        sql += " ORDER BY l.id"
        for row in db.execute(sql, values):
            yield {"id": row["id"], "lemma": row["lemma"], "pos": row["pos"],
                   "contexts": sources_for_lexeme(db, row["id"])}
    else:
        sql = "SELECT p.id,p.markdown FROM pages p"
        values = []
        if book:
            sql += " JOIN books b ON b.id=p.book_id WHERE b.title=?"
            values.append(book)
        sql += " ORDER BY p.id"
        for row in db.execute(sql, values):
            yield {"id": row["id"], "markdown": row["markdown"]}


def chunks(items, count: int):
    for offset in range(0, len(items), count):
        yield items[offset:offset + count]


def inventory(db_path: Path):
    with read_database(db_path) as db:
        counts = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                  for name in ("books", "pages", "lexemes", "senses", "patterns",
                               "examples", "lexeme_relations", "expression_components")}
        counts["human_status"] = {r[0]: r[1] for r in db.execute(
            "SELECT human_status,COUNT(*) FROM lexemes GROUP BY human_status")}
        counts["integrity_check"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        return counts


def prepare(db_path: Path, workspace: Path):
    if (workspace / "manifest.json").exists():
        raise RuntimeError("Workspace already prepared; select a new directory")
    workspace.mkdir(parents=True, exist_ok=True)
    dest = workspace / "source_snapshot.db"
    if dest.exists():
        raise RuntimeError("Snapshot target exists; refusing to overwrite")
    # Migrations can enable WAL. Build in a disposable directory, then seal the
    # fully committed logical database into an independent DELETE-mode file.
    # VACUUM INTO does not need an exclusive journal-mode switch on the WAL DB.
    with tempfile.TemporaryDirectory(prefix="snapshot-build-", dir=workspace) as temp:
        working = Path(temp) / "working.db"
        snapshot(db_path, working)
        with write_database(working) as db:
            seed_tags(db)
        with read_database(working) as db:
            db.execute("VACUUM INTO ?", (str(dest),))
    # The sealed database has no WAL sidecars; reading it cannot later alter
    # the hashed main file through a checkpoint.
    with read_database(dest) as db:
        if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise RuntimeError("Sealed snapshot is not using DELETE journaling")
    counts = inventory(dest)
    manifest = {"snapshot_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                "taxonomy_version": TAXONOMY_VERSION, "source": str(db_path.resolve()),
                "counts": counts}
    atomic_json(workspace / "manifest.json", manifest)
    return manifest


def checked_workspace(workspace: Path) -> Path:
    source = workspace / "source_snapshot.db"
    manifest = workspace / "manifest.json"
    if not source.is_file() or not manifest.is_file():
        raise RuntimeError("First run the prepare command")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("taxonomy_version") != TAXONOMY_VERSION:
        raise RuntimeError("Taxonomy version has changed since preparation")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != record.get("snapshot_sha256"):
        raise RuntimeError("Source snapshot was modified; refusing to continue")
    return source


def staged_files(workspace: Path, stage: str):
    return sorted((workspace / "batches" / stage).glob("*.json"))

