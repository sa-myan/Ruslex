"""Standalone construction reference; permission-gated review status."""
from __future__ import annotations

from django.db import connections, transaction
from .query_helpers import LEXICON, legacy_rows, paginate

STATUSES = {"unreviewed", "kept", "hidden", "followup"}


def installed() -> bool:
    with connections[LEXICON].cursor() as cur:
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='constructions'")
        return cur.fetchone() is not None


def _attach_details(records: list[dict]) -> None:
    """Hydrate both lists and review cards with source-backed evidence."""
    ids = [record["id"] for record in records]
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    examples = legacy_rows(
        "SELECT construction_id,russian,english FROM construction_examples "
        f"WHERE construction_id IN ({placeholders}) ORDER BY id", ids)
    pages = legacy_rows(
        "SELECT a.construction_id,a.page_id,a.surface,b.title,b.edition,"
        "p.pdf_page,p.printed_page FROM construction_attestations a "
        "JOIN pages p ON p.id=a.page_id JOIN books b ON b.id=p.book_id "
        f"WHERE a.construction_id IN ({placeholders}) ORDER BY b.title,p.pdf_page", ids)
    expressions = legacy_rows(
        "SELECT x.construction_id,x.expression_id AS id,l.lemma,x.evidence "
        "FROM construction_expression_links x JOIN lexemes l ON l.id=x.expression_id "
        f"WHERE x.construction_id IN ({placeholders}) AND l.human_status!='hidden' "
        "ORDER BY l.lemma", ids)
    for record in records:
        record["examples"] = [
            {"russian": e["russian"], "english": e["english"]}
            for e in examples if e["construction_id"] == record["id"]]
        record["sources"] = [
            {k: v for k, v in e.items() if k != "construction_id"}
            for e in pages if e["construction_id"] == record["id"]]
        record["expressions"] = [
            {k: v for k, v in e.items() if k != "construction_id"}
            for e in expressions if e["construction_id"] == record["id"]]


def list_records(params, *, can_review: bool) -> dict:
    try:
        page = int(params.get("page", "1"))
        size = int(params.get("page_size", "20"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid page or page_size") from exc
    if page < 1 or not 1 <= size <= 100:
        raise ValueError("Invalid page or page_size")
    status = params.get("status", "all" if can_review else "visible")
    if status not in STATUSES | {"all", "visible"}:
        raise ValueError("Unknown construction status")
    if not can_review and status not in ("visible", "kept"):
        status = "visible"
    search = params.get("q", "").strip()
    if len(search) > 150:
        raise ValueError("Search is too long")
    if not installed():
        return {"installed": False, **paginate([], page, size)}
    clauses, values = [], []
    # Unreviewed/deferred AI proposals must never appear in public results.
    if not can_review or status == "visible":
        clauses.append("c.human_status = 'kept'")
    elif status != "all":
        clauses.append("c.human_status = %s")
        values.append(status)
    if search:
        clauses.append("(c.pattern LIKE %s OR c.meaning LIKE %s)")
        values.extend([f"%{search}%", f"%{search}%"])
    condition = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    records = legacy_rows(
        "SELECT c.id,c.pattern,c.meaning,c.grammar,c.human_status,c.notes "
        "FROM constructions c" + condition + " ORDER BY c.pattern_key,c.id", values)
    page_data = paginate(records, page, size)
    _attach_details(page_data["items"])
    return {"installed": True, **page_data}


def next_review(queue: str = "pending", after: int = 0) -> dict:
    """Review one unpublished construction at a time."""
    if queue not in {"pending", "deferred", "all"}:
        raise ValueError("Unknown construction review queue")
    if type(after) is not int or after < 0:
        raise ValueError("Invalid construction review cursor")
    if not installed():
        return {"installed": False, "item": None, "total": 0}
    where = {
        "pending": "human_status='unreviewed'",
        "deferred": "human_status='followup'",
        "all": "human_status IN ('unreviewed','followup')",
    }[queue]
    total = legacy_rows(f"SELECT COUNT(*) AS n FROM constructions WHERE {where}")[0]["n"]
    base = ("SELECT id,pattern,meaning,grammar,human_status,notes "
            f"FROM constructions WHERE {where}")
    rows = legacy_rows(base + " AND id>%s ORDER BY id LIMIT 1", [after])
    if not rows:
        rows = legacy_rows(base + " ORDER BY id LIMIT 1")
    _attach_details(rows)
    return {"installed": True, "item": rows[0] if rows else None,
            "total": total}


@transaction.atomic(using=LEXICON)
def update_status(construction_id: int, status: object,
                  notes: object | None = None) -> dict:
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Invalid construction review status")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 1000):
        raise ValueError("Review note must be text of at most 1000 characters")
    if not installed():
        raise RuntimeError("Construction schema is not installed")
    with connections[LEXICON].cursor() as cur:
        if notes is None:
            cur.execute("UPDATE constructions SET human_status=%s WHERE id=%s",
                        [status, construction_id])
        else:
            cur.execute(
                "UPDATE constructions SET human_status=%s,notes=%s WHERE id=%s",
                [status, notes.strip(), construction_id])
        if not cur.rowcount:
            raise LookupError("Construction not found")
    return {"id": construction_id, "human_status": status}
