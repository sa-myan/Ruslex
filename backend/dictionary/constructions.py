"""Standalone construction reference; permission-gated review status."""
from __future__ import annotations

from django.db import connections, transaction
from .query_helpers import LEXICON, legacy_rows, paginate

STATUSES = {"unreviewed", "kept", "hidden", "followup"}


def installed() -> bool:
    with connections[LEXICON].cursor() as cur:
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='constructions'")
        return cur.fetchone() is not None


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
    if not can_review or status == "visible":
        clauses.append("c.human_status != 'hidden'")
    elif status != "all":
        clauses.append("c.human_status = %s")
        values.append(status)
    if search:
        clauses.append("(c.pattern LIKE %s OR c.meaning LIKE %s)")
        values.extend([f"%{search}%", f"%{search}%"])
    condition = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    records = legacy_rows(
        "SELECT c.id,c.pattern,c.meaning,c.grammar,c.human_status "
        "FROM constructions c" + condition + " ORDER BY c.pattern_key,c.id", values)
    page_data = paginate(records, page, size)
    ids = [r["id"] for r in page_data["items"]]
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        examples = legacy_rows(
            "SELECT construction_id,russian,english FROM construction_examples "
            f"WHERE construction_id IN ({placeholders}) ORDER BY id", ids)
        pages = legacy_rows(
            "SELECT a.construction_id,a.page_id,a.surface,b.title,p.pdf_page "
            "FROM construction_attestations a "
            "JOIN pages p ON p.id=a.page_id JOIN books b ON b.id=p.book_id "
            f"WHERE a.construction_id IN ({placeholders}) ORDER BY b.title,p.pdf_page", ids)
        expressions = legacy_rows(
            "SELECT x.construction_id,x.expression_id AS id,l.lemma,x.evidence "
            "FROM construction_expression_links x JOIN lexemes l ON l.id=x.expression_id "
            f"WHERE x.construction_id IN ({placeholders}) AND l.human_status!='hidden' "
            "ORDER BY l.lemma", ids)
        for row in page_data["items"]:
            row["examples"] = [
                {"russian": e["russian"], "english": e["english"]}
                for e in examples if e["construction_id"] == row["id"]]
            row["sources"] = [
                {k: v for k, v in e.items() if k != "construction_id"}
                for e in pages if e["construction_id"] == row["id"]]
            row["expressions"] = [
                {k: v for k, v in e.items() if k != "construction_id"}
                for e in expressions if e["construction_id"] == row["id"]]
    return {"installed": True, **page_data}


@transaction.atomic(using=LEXICON)
def update_status(construction_id: int, status: object) -> dict:
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Invalid construction review status")
    if not installed():
        raise RuntimeError("Construction schema is not installed")
    with connections[LEXICON].cursor() as cur:
        cur.execute("UPDATE constructions SET human_status=%s WHERE id=%s",
                    [status, construction_id])
        if not cur.rowcount:
            raise LookupError("Construction not found")
    return {"id": construction_id, "human_status": status}
