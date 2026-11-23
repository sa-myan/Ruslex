"""Dictionary search filters, relevance ranking, and results previews.

The supplied lexicon is small enough to score matches in Python. Search tiers
and result ordering intentionally remain compatible with the v3 fixtures.
"""

from collections import defaultdict
import re

from .catalog import PARTS_OF_SPEECH, STATUSES
from .models import Lexeme, Sense
from .query_helpers import (
    LEXICON, _page_counts, _sql_placeholders, legacy_rows, paginate,
    tags_for_senses,
)
from .search_rank import english_quality, folded, score

PAGE_FILTERS = (
    "book_id", "pdf_page", "printed_page", "pdf_page_min", "pdf_page_max",
    "printed_page_min", "printed_page_max",
)


def summaries(words: list, matching: dict | None = None) -> list[dict]:
    """Serialize the entries on one results page (including sense previews)."""
    word_ids = [entry.id for entry in words]
    if not word_ids:
        return []

    senses_by_word = defaultdict(list)
    sense_ids = []
    active_senses = Sense.objects.using(LEXICON).filter(
        lexeme_id__in=word_ids, active=1
    ).order_by("id")
    for item in active_senses:
        senses_by_word[item.lexeme_id].append(item)
        sense_ids.append(item.id)

    tags_by_sense = tags_for_senses(sense_ids)
    counts = _page_counts(word_ids)
    results = []

    for entry in words:
        senses = senses_by_word[entry.id]
        if matching and matching.get("english"):
            query = matching["query"]
            senses = sorted(
                senses,
                key=lambda item: (-english_quality(item.meaning, query), item.id),
            )

        unique_tags = {
            (tag["id"], tag["name"], tag["category"])
            for item in senses
            for tag in tags_by_sense.get(item.id, [])
        }
        results.append(
            {
                "id": entry.id,
                "lemma": entry.lemma,
                "pos": entry.pos,
                "entry_type": entry.entry_type,
                "aspect": entry.aspect,
                "animacy": entry.animacy,
                "human_status": entry.human_status,
                "page_count": counts.get(entry.id, 0),
                "gloss_preview": " · ".join(item.meaning for item in senses[:2]) or None,
                "tags": [
                    {"id": tag_id, "name": name, "category": category}
                    for tag_id, name, category in sorted(
                        unique_tags, key=lambda item: (item[2], item[1])
                    )
                ],
            }
        )
    return results


def _search_paging(params) -> tuple[int, int]:
    try:
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 40))
        if page < 1 or page > 100000 or not 1 <= page_size <= 100:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid pagination") from exc
    return page, page_size


def _search_queryset(params, allow_review: bool):
    """Apply lexical filters and status visibility before optional SQL joins."""
    status = params.get("status", "visible") if allow_review else "visible"
    if status not in (STATUSES | {"visible", "all"}):
        raise ValueError("Invalid status")

    queryset = Lexeme.objects.using(LEXICON).all().order_by("id")
    if status == "visible":
        queryset = queryset.exclude(human_status="hidden")
    elif status != "all":
        queryset = queryset.filter(human_status=status)

    pos = params.get("pos")
    kind = params.get("entry_type")
    if pos:
        if pos not in {code for code, _ in PARTS_OF_SPEECH}:
            raise ValueError("Unknown part of speech")
        queryset = queryset.filter(pos=pos)
    if kind:
        if kind not in {"word", "expression"}:
            raise ValueError("Invalid entry type")
        queryset = queryset.filter(entry_type=kind)
    return queryset


def _selected_tag_ids(params) -> set[int]:
    ids = set()
    for raw in params.getlist("tag_id"):
        try:
            tag_id = int(raw)
            if tag_id <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid tag ID") from exc
        ids.add(tag_id)
    return ids


def _word_ids_with_tags(tag_ids: set[int]) -> set[int]:
    """All selected tags must occur on the SAME active sense."""
    tags = sorted(tag_ids)
    rows = legacy_rows(
        f"""SELECT s.lexeme_id
            FROM senses s
            JOIN sense_tags st ON st.sense_id = s.id
            WHERE s.active = 1 AND st.tag_id IN ({_sql_placeholders(len(tags))})
            GROUP BY s.id
            HAVING COUNT(DISTINCT st.tag_id) = %s""",
        [*tags, len(tags)],
    )
    return {row["lexeme_id"] for row in rows}


def _word_ids_for_pages(params) -> set[int] | None:
    """Apply an allowlisted set of page filters; never use raw keys as SQL."""
    supplied = {key: params.get(key) for key in PAGE_FILTERS if params.get(key)}
    if not supplied:
        return None

    conditions = []
    arguments = []
    for key, raw in supplied.items():
        try:
            number = int(raw)
            if number < 1:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid source page") from exc

        column = "p.book_id" if key == "book_id" else f"p.{key.replace('_min', '').replace('_max', '')}"
        operator = ">=" if key.endswith("_min") else "<=" if key.endswith("_max") else "="
        conditions.append(f"{column}{operator}%s")
        arguments.append(number)

    for prefix in ("pdf_page", "printed_page"):
        minimum, maximum = f"{prefix}_min", f"{prefix}_max"
        if minimum in supplied and maximum in supplied:
            if int(supplied[minimum]) > int(supplied[maximum]):
                raise ValueError("Page range start must not exceed its end")

    rows = legacy_rows(
        "SELECT DISTINCT lp.lexeme_id FROM lexeme_pages lp "
        "JOIN pages p ON p.id=lp.page_id WHERE " + " AND ".join(conditions),
        arguments,
    )
    return {row["lexeme_id"] for row in rows}


def _rank_words(words: list, query: str, english: bool) -> list:
    matching_senses = defaultdict(list)
    for item in Sense.objects.using(LEXICON).filter(
        lexeme_id__in=[entry.id for entry in words], active=1
    ):
        matching_senses[item.lexeme_id].append(item)

    ranked = []
    for entry in words:
        tier = score(entry.lemma, matching_senses[entry.id], query, english=english)
        if tier is None:
            continue
        ranked.append(
            (tier, len(entry.lemma), folded(entry.lemma), entry.id, entry)
        )
    return [result[-1] for result in sorted(ranked)]


def search(params, *, allow_review: bool = False) -> dict:
    query = folded(params.get("q", "").strip())
    if len(query) > 200:
        raise ValueError("Search text is too long")

    page, size = _search_paging(params)
    words = list(_search_queryset(params, allow_review))
    allowed_ids = {entry.id for entry in words}

    tag_ids = _selected_tag_ids(params)
    if tag_ids:
        allowed_ids.intersection_update(_word_ids_with_tags(tag_ids))

    page_ids = _word_ids_for_pages(params)
    if page_ids is not None:
        allowed_ids.intersection_update(page_ids)

    words = [entry for entry in words if entry.id in allowed_ids]
    english = bool(re.search("[a-z]", query)) and not bool(re.search("[а-я]", query))
    if query:
        words = _rank_words(words, query, english)

    result = paginate(words, page, size)
    result["items"] = summaries(result["items"], {"english": english, "query": query})
    return result
