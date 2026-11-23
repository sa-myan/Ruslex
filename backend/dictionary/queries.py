"""Read-only queries. Complex legacy join tables stay in this one module.

Search is intentionally small-data-friendly: the supplied dictionary has 1,710
entries. Relevance is scored in Python for Unicode-correct Russian and English
word boundaries. A future large corpus can replace the search implementation
without touching HTTP views or the data model.
"""
from collections import defaultdict
import math
import re
from .search_rank import folded,english_quality,score

from django.db import connections
from django.db.models import Q
from .catalog import PARTS_OF_SPEECH, STATUSES
from .models import Book, Example, ExpressionComponent, ExternalLink, Lexeme, Page, Pattern, Relation, Review, Sense, Tag


def legacy_rows(sql, args=()):
    with connections["lexicon"].cursor() as cursor:
        cursor.execute(sql, args)
        names = [col[0] for col in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def one(sql, args=()):
    return legacy_rows(sql, args)[0]


def paginate(items, page, page_size):
    total = len(items)
    page_count = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    return {"items": items[offset:offset + page_size], "total": total, "page": page,
            "page_size": page_size, "pages": page_count}


def tags_for_senses(sense_ids):
    if not sense_ids:
        return {}
    result = defaultdict(list)
    # SQLite parameter limit stays comfortably below 999: one lexeme at a time.
    ids = list(dict.fromkeys(sense_ids))
    for start in range(0, len(ids), 400):
        group = ids[start:start + 400]
        marks = ",".join(["%s"] * len(group))
        rows = legacy_rows(f"""SELECT st.sense_id,t.id,t.name,t.category
              FROM sense_tags st JOIN tags t ON t.id=st.tag_id
              WHERE st.sense_id IN ({marks}) ORDER BY t.category,t.name""", group)
        for row in rows:
            key = row.pop("sense_id")
            result[key].append(row)
    return result


def summaries(words, matching=None):
    ids = [w.id for w in words]
    if not ids:
        return []
    active_senses = Sense.objects.using("lexicon").filter(lexeme_id__in=ids, active=1).order_by("id")
    per_word = defaultdict(list)
    sense_ids = []
    for sense in active_senses:
        per_word[sense.lexeme_id].append(sense)
        sense_ids.append(sense.id)
    per_sense_tags = tags_for_senses(sense_ids)
    counts = {}
    for start in range(0, len(ids), 400):
        group = ids[start:start + 400]
        marks = ",".join(["%s"] * len(group))
        for row in legacy_rows(f"SELECT lexeme_id,COUNT(DISTINCT page_id) AS n FROM lexeme_pages WHERE lexeme_id IN ({marks}) GROUP BY lexeme_id", group):
            counts[row["lexeme_id"]] = row["n"]
    output = []
    for w in words:
        senses = per_word[w.id]
        if matching and matching.get("english"):
            q = matching["query"]
            senses = sorted(senses, key=lambda s: (-english_quality(s.meaning, q), s.id))
        unique_tags = {(t["id"], t["name"], t["category"]) for s in senses for t in per_sense_tags.get(s.id, [])}
        output.append({"id": w.id, "lemma": w.lemma, "pos": w.pos,
            "entry_type": w.entry_type, "aspect": w.aspect, "animacy": w.animacy,
            "human_status": w.human_status, "page_count": counts.get(w.id, 0),
            "gloss_preview": " · ".join(s.meaning for s in senses[:2]) or None,
            "tags": [{"id": i, "name": n, "category": c} for i, n, c in sorted(unique_tags, key=lambda t: (t[2], t[1]))]})
    return output


def search(params, *, allow_review=False):
    q = folded(params.get("q", "").strip())
    if len(q) > 200:
        raise ValueError("Search text is too long")
    status = params.get("status", "visible") if allow_review else "visible"
    if status not in (STATUSES | {"visible", "all"}):
        raise ValueError("Invalid status")
    try:
        page = int(params.get("page", 1))
        size = int(params.get("page_size", 40))
        if page < 1 or page > 100000 or not (1 <= size <= 100):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Invalid pagination")
    queryset = Lexeme.objects.using("lexicon").all().order_by("id")
    if status == "visible":
        queryset = queryset.exclude(human_status="hidden")
    elif status != "all":
        queryset = queryset.filter(human_status=status)
    pos, kind = params.get("pos"), params.get("entry_type")
    if pos:
        if pos not in {p for p, _ in PARTS_OF_SPEECH}:
            raise ValueError("Unknown part of speech")
        queryset = queryset.filter(pos=pos)
    if kind:
        if kind not in {"word", "expression"}:
            raise ValueError("Invalid entry type")
        queryset = queryset.filter(entry_type=kind)
    words = list(queryset)
    filtered_ids = {w.id for w in words}
    tag_ids = set()
    for raw in params.getlist("tag_id"):
        try:
            tag_id = int(raw)
            if tag_id <= 0: raise ValueError
            tag_ids.add(tag_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid tag ID")
    if tag_ids:
        # Every selected tag must occur on the SAME active sense.
        marks = ",".join(["%s"] * len(tag_ids))
        tagged = legacy_rows(f"""SELECT s.lexeme_id FROM senses s
            JOIN sense_tags st ON st.sense_id=s.id WHERE s.active=1
            AND st.tag_id IN ({marks}) GROUP BY s.id
            HAVING COUNT(DISTINCT st.tag_id)=%s""", [*sorted(tag_ids), len(tag_ids)])
        filtered_ids.intersection_update(r["lexeme_id"] for r in tagged)
    pages = {key: params.get(key) for key in (
        "book_id", "pdf_page", "printed_page", "pdf_page_min", "pdf_page_max",
        "printed_page_min", "printed_page_max") if params.get(key)}
    if pages:
        where = []
        args = []
        for key, raw in pages.items():
            try:
                number = int(raw)
                if number < 1: raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Invalid source page")
            col = "p.book_id" if key == "book_id" else f"p.{key.replace('_min','').replace('_max','')}"
            operator = ">=" if key.endswith("_min") else "<=" if key.endswith("_max") else "="
            where.append(f"{col}{operator}%s")
            args.append(number)
        for base in ("pdf_page", "printed_page"):
            if f"{base}_min" in pages and f"{base}_max" in pages and int(pages[f"{base}_min"]) > int(pages[f"{base}_max"]):
                raise ValueError("Page range start must not exceed its end")
        page_words = legacy_rows("SELECT DISTINCT lp.lexeme_id FROM lexeme_pages lp JOIN pages p ON p.id=lp.page_id WHERE " + " AND ".join(where), args)
        filtered_ids.intersection_update(r["lexeme_id"] for r in page_words)
    words = [w for w in words if w.id in filtered_ids]
    english = bool(re.search("[a-z]", q)) and not bool(re.search("[а-я]", q))
    matching_senses = defaultdict(list)
    if q:
        for sense in Sense.objects.using("lexicon").filter(lexeme_id__in=[w.id for w in words], active=1):
            matching_senses[sense.lexeme_id].append(sense)
        ranked = []
        for w in words:
            lemma = folded(w.lemma)
            senses = matching_senses[w.id]
            tier = score(w.lemma, senses, q, english=english)
            if tier is not None:
                ranked.append((tier, len(w.lemma), folded(w.lemma), w.id, w))
        words = [r[-1] for r in sorted(ranked)]
    paged = paginate(words, page, size)
    paged["items"] = summaries(paged["items"], {"english": english, "query": q})
    return paged


def detail(word_id, *, private_notes=False):
    w = Lexeme.objects.using("lexicon").filter(pk=word_id).first()
    if w is None:
        raise LookupError("Entry not found")
    senses = list(Sense.objects.using("lexicon").filter(lexeme_id=word_id).order_by("-active", "id"))
    sense_tags = tags_for_senses([s.id for s in senses])
    examples = defaultdict(list)
    for x in Example.objects.using("lexicon").filter(sense_id__in=[s.id for s in senses]).order_by("-active", "id"):
        examples[x.sense_id].append({"id":x.id,"sense_id":x.sense_id,"russian":x.russian,"english":x.english,"active":x.active})
    patterns = defaultdict(list)
    for x in Pattern.objects.using("lexicon").filter(sense_id__in=[s.id for s in senses]).order_by("-active", "id"):
        patterns[x.sense_id].append({"id":x.id,"sense_id":x.sense_id,"pattern":x.pattern,"active":x.active})
    view_senses = [{"id":s.id,"lexeme_id":s.lexeme_id,"meaning":s.meaning,"description":s.description,
                    "active":s.active,"tags":sense_tags.get(s.id,[]),
                    "examples":examples[s.id],"patterns":patterns[s.id]} for s in senses]
    links = list(ExternalLink.objects.using("lexicon").filter(lexeme_id=word_id).order_by("id").values("id","lexeme_id","label","url"))
    relation_objects = list(Relation.objects.using("lexicon").filter(Q(source_lexeme_id=word_id)|Q(target_lexeme_id=word_id)).order_by("id"))
    other_ids = {r.target_lexeme_id if r.source_lexeme_id==word_id else r.source_lexeme_id for r in relation_objects}
    other_words = Lexeme.objects.using("lexicon").in_bulk(other_ids)
    other_sense_ids = {r.target_sense_id if r.source_lexeme_id==word_id else r.source_sense_id for r in relation_objects}
    other_senses = Sense.objects.using("lexicon").in_bulk([n for n in other_sense_ids if n])
    relation_rows = []
    for r in relation_objects:
        outgoing = r.source_lexeme_id == word_id
        other = other_words[r.target_lexeme_id if outgoing else r.source_lexeme_id]
        osid = r.target_sense_id if outgoing else r.source_sense_id
        relation_rows.append({"id":r.id,"source_lexeme_id":r.source_lexeme_id,
            "target_lexeme_id":r.target_lexeme_id,"relation_type":r.relation_type,
            "source_sense_id":r.source_sense_id,"target_sense_id":r.target_sense_id,
            "direction":"outgoing" if outgoing else "incoming", "notes":r.notes if private_notes else "",
            "other_id":other.id,"other_lemma":other.lemma,"other_pos":other.pos,
            "other_aspect":other.aspect,"other_entry_type":other.entry_type,
            "other_sense_meaning":other_senses[osid].meaning if osid in other_senses else None})
    relation_rows.sort(key=lambda x: (x["relation_type"] != "aspect_pair", x["relation_type"], x["other_lemma"], x["id"]))
    components = list(ExpressionComponent.objects.using("lexicon").filter(expression_id=word_id).order_by("position", "id"))
    component_words = Lexeme.objects.using("lexicon").in_bulk({c.word_id for c in components})
    component_rows = [{"id":c.id,"expression_id":c.expression_id,"word_id":c.word_id,"position":c.position,
                       "surface":c.surface,"notes":c.notes if private_notes else "",
                       "word_lemma":component_words[c.word_id].lemma,"word_pos":component_words[c.word_id].pos} for c in components]
    used_in = list(ExpressionComponent.objects.using("lexicon").filter(word_id=word_id).order_by("position"))
    used_expressions = Lexeme.objects.using("lexicon").in_bulk({c.expression_id for c in used_in})
    occurs_in = [{"id":c.id,"position":c.position,"surface":c.surface,"expression_id":c.expression_id,
                  "expression_lemma":used_expressions[c.expression_id].lemma} for c in used_in]
    sources = legacy_rows("""SELECT b.id book_id,b.title,b.edition,p.pdf_page,p.printed_page,
        lp.surface,lp.context,lp.count FROM lexeme_pages lp JOIN pages p ON p.id=lp.page_id
        JOIN books b ON b.id=p.book_id WHERE lp.lexeme_id=%s ORDER BY RANDOM() LIMIT 10""", [word_id])
    totals = one("SELECT COUNT(*) n,COUNT(DISTINCT page_id) p FROM lexeme_pages WHERE lexeme_id=%s", [word_id])
    return {"id":w.id,"lemma":w.lemma,"pos":w.pos,"entry_type":w.entry_type,"aspect":w.aspect,
        "animacy":w.animacy,"human_status":w.human_status,"notes":w.notes,
        "created_at":w.created_at,"senses":view_senses,"external_links":links,"relations":relation_rows,
        "components":component_rows,"occurs_in":occurs_in,
        "sources":sources,"sources_total":totals["n"],"source_page_count":totals["p"]}


def references(word_id, page=1, size=40, book_id=None, pdf_page=None):
    if not Lexeme.objects.using("lexicon").filter(pk=word_id).exists():
        raise LookupError("Entry not found")
    where = ["lp.lexeme_id=%s"]
    args = [word_id]
    if book_id:
        where.append("p.book_id=%s")
        args.append(book_id)
    if pdf_page:
        where.append("p.pdf_page=%s")
        args.append(pdf_page)
    clause = " AND ".join(where)
    rows = legacy_rows("""SELECT b.id book_id,b.title,b.edition,p.id page_id,p.pdf_page,
        p.printed_page,lp.surface,lp.context,lp.count FROM lexeme_pages lp
        JOIN pages p ON p.id=lp.page_id JOIN books b ON b.id=p.book_id WHERE """ + clause +
        " ORDER BY b.title,b.id,p.pdf_page,lp.surface",args)
    return paginate(rows,page,size)


def reference_pages(word_id,page=1,size=60):
    if not Lexeme.objects.using("lexicon").filter(pk=word_id).exists():
        raise LookupError("Entry not found")
    rows=legacy_rows("""SELECT b.id book_id,b.title,b.edition,p.id page_id,p.pdf_page,
        p.printed_page,SUM(lp.count) occurrence_count FROM lexeme_pages lp
        JOIN pages p ON p.id=lp.page_id JOIN books b ON b.id=p.book_id
        WHERE lp.lexeme_id=%s GROUP BY p.id ORDER BY b.title,b.id,p.pdf_page""", [word_id])
    return paginate(rows,page,size)


def books():
    counts = {r["book_id"]:r["n"] for r in legacy_rows("SELECT book_id,COUNT(*) n FROM pages GROUP BY book_id")}
    return [{"id":b.id,"title":b.title,"edition":b.edition,"page_count":counts.get(b.id,0)}
            for b in Book.objects.using("lexicon").order_by("title", "edition", "id")]


def tags():
    counts={r["id"]:r for r in legacy_rows("""SELECT t.id,COUNT(DISTINCT CASE WHEN s.active=1 THEN s.lexeme_id END) word_count,
       COUNT(st.sense_id) sense_count FROM tags t LEFT JOIN sense_tags st ON st.tag_id=t.id
       LEFT JOIN senses s ON s.id=st.sense_id GROUP BY t.id""")}
    return [{"id":t.id,"name":t.name,"category":t.category,
             "word_count":counts[t.id]["word_count"],"sense_count":counts[t.id]["sense_count"]}
            for t in Tag.objects.using("lexicon").order_by("category","name")]


def stats():
    return {"counts": {t:one(f"SELECT COUNT(*) n FROM {t}")["n"] for t in
                           ("books","pages","lexemes","senses","examples","patterns")},
            "word_status": {r["human_status"]:r["n"] for r in legacy_rows("SELECT human_status,COUNT(*) n FROM lexemes GROUP BY human_status")},
            "review_status": {r["status"]:r["n"] for r in legacy_rows("SELECT status,COUNT(*) n FROM reviews GROUP BY status")}}


def next_review(status="unreviewed", after=0):
    if status not in (STATUSES | {"all"}):
        raise ValueError("Invalid review status")
    q = Lexeme.objects.using("lexicon")
    if status != "all":
        q=q.filter(human_status=status)
    total=q.count()
    obj=q.filter(id__gt=after).order_by("id").first() or q.order_by("id").first()
    if obj is None:
        return {"word":None,"total":total,"sources":[]}
    return {"word":{"id":obj.id,"lemma":obj.lemma,"pos":obj.pos,"human_status":obj.human_status},
            "total":total,"sources":detail(obj.id)["sources"]}
