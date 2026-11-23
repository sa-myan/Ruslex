"""Serialize complete dictionary entries without modifying data.

Entry notes are public. Notes on relations and expression constituents remain
private to authenticated readers, as established in the existing API.
"""

from collections import defaultdict

from django.db.models import Q

from .models import (
    Example, ExpressionComponent, ExternalLink, Lexeme, Pattern, Relation, Sense,
)
from .query_helpers import LEXICON, legacy_rows, one, tags_for_senses


def _sense_rows(word_id: int) -> list[dict]:
    senses = list(
        Sense.objects.using(LEXICON)
        .filter(lexeme_id=word_id)
        .order_by("-active", "id")
    )
    ids = [item.id for item in senses]
    tags_by_sense = tags_for_senses(ids)

    examples = defaultdict(list)
    example_records = Example.objects.using(LEXICON).filter(
        sense_id__in=ids
    ).order_by("-active", "id")
    for example in example_records:
        examples[example.sense_id].append(
            {
                "id": example.id,
                "sense_id": example.sense_id,
                "russian": example.russian,
                "english": example.english,
                "active": example.active,
            }
        )

    patterns = defaultdict(list)
    pattern_records = Pattern.objects.using(LEXICON).filter(
        sense_id__in=ids
    ).order_by("-active", "id")
    for pattern in pattern_records:
        patterns[pattern.sense_id].append(
            {
                "id": pattern.id,
                "sense_id": pattern.sense_id,
                "pattern": pattern.pattern,
                "active": pattern.active,
            }
        )

    return [
        {
            "id": item.id,
            "lexeme_id": item.lexeme_id,
            "meaning": item.meaning,
            "description": item.description,
            "active": item.active,
            "tags": tags_by_sense.get(item.id, []),
            "examples": examples[item.id],
            "patterns": patterns[item.id],
        }
        for item in senses
    ]


def _relation_rows(word_id: int, private_notes: bool) -> list[dict]:
    relations = list(
        Relation.objects.using(LEXICON)
        .filter(Q(source_lexeme_id=word_id) | Q(target_lexeme_id=word_id))
        .order_by("id")
    )
    other_ids = {
        rel.target_lexeme_id if rel.source_lexeme_id == word_id else rel.source_lexeme_id
        for rel in relations
    }
    others = Lexeme.objects.using(LEXICON).in_bulk(other_ids)
    other_sense_ids = {
        rel.target_sense_id if rel.source_lexeme_id == word_id else rel.source_sense_id
        for rel in relations
    }
    other_senses = Sense.objects.using(LEXICON).in_bulk(
        [item for item in other_sense_ids if item]
    )

    rows = []
    for relation in relations:
        outgoing = relation.source_lexeme_id == word_id
        other_id = relation.target_lexeme_id if outgoing else relation.source_lexeme_id
        other = others[other_id]
        other_sense_id = relation.target_sense_id if outgoing else relation.source_sense_id
        rows.append(
            {
                "id": relation.id,
                "source_lexeme_id": relation.source_lexeme_id,
                "target_lexeme_id": relation.target_lexeme_id,
                "relation_type": relation.relation_type,
                "source_sense_id": relation.source_sense_id,
                "target_sense_id": relation.target_sense_id,
                "direction": "outgoing" if outgoing else "incoming",
                # Only entry notes are public. Relationship notes stay private.
                "notes": relation.notes if private_notes else "",
                "other_id": other.id,
                "other_lemma": other.lemma,
                "other_pos": other.pos,
                "other_aspect": other.aspect,
                "other_entry_type": other.entry_type,
                "other_sense_meaning": (
                    other_senses[other_sense_id].meaning
                    if other_sense_id in other_senses
                    else None
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["relation_type"] != "aspect_pair",
            row["relation_type"],
            row["other_lemma"],
            row["id"],
        )
    )
    return rows


def _component_rows(word_id: int, private_notes: bool) -> tuple[list[dict], list[dict]]:
    components = list(
        ExpressionComponent.objects.using(LEXICON)
        .filter(expression_id=word_id)
        .order_by("position", "id")
    )
    component_words = Lexeme.objects.using(LEXICON).in_bulk(
        {item.word_id for item in components}
    )
    component_rows = [
        {
            "id": item.id,
            "expression_id": item.expression_id,
            "word_id": item.word_id,
            "position": item.position,
            "surface": item.surface,
            "notes": item.notes if private_notes else "",
            "word_lemma": component_words[item.word_id].lemma,
            "word_pos": component_words[item.word_id].pos,
        }
        for item in components
    ]

    used_in = list(
        ExpressionComponent.objects.using(LEXICON)
        .filter(word_id=word_id)
        .order_by("position")
    )
    expressions = Lexeme.objects.using(LEXICON).in_bulk(
        {item.expression_id for item in used_in}
    )
    occurs_in = [
        {
            "id": item.id,
            "position": item.position,
            "surface": item.surface,
            "expression_id": item.expression_id,
            "expression_lemma": expressions[item.expression_id].lemma,
        }
        for item in used_in
    ]
    return component_rows, occurs_in


def _entry_source_sample(word_id: int) -> tuple[list[dict], dict]:
    sample = legacy_rows(
        """SELECT b.id book_id, b.title, b.edition, p.pdf_page, p.printed_page,
                  lp.surface, lp.context, lp.count
           FROM lexeme_pages lp
           JOIN pages p ON p.id = lp.page_id
           JOIN books b ON b.id = p.book_id
           WHERE lp.lexeme_id = %s ORDER BY RANDOM() LIMIT 10""",
        [word_id],
    )
    totals = one(
        "SELECT COUNT(*) n, COUNT(DISTINCT page_id) p "
        "FROM lexeme_pages WHERE lexeme_id=%s",
        [word_id],
    )
    return sample, totals


def detail(word_id: int, *, private_notes: bool = False) -> dict:
    entry = Lexeme.objects.using(LEXICON).filter(pk=word_id).first()
    if entry is None:
        raise LookupError("Entry not found")

    components, occurs_in = _component_rows(word_id, private_notes)
    sources, totals = _entry_source_sample(word_id)
    links = list(
        ExternalLink.objects.using(LEXICON)
        .filter(lexeme_id=word_id)
        .order_by("id")
        .values("id", "lexeme_id", "label", "url")
    )
    return {
        "id": entry.id,
        "lemma": entry.lemma,
        "pos": entry.pos,
        "entry_type": entry.entry_type,
        "aspect": entry.aspect,
        "animacy": entry.animacy,
        "human_status": entry.human_status,
        "notes": entry.notes,  # Public entry notes, regardless of authentication.
        "created_at": entry.created_at,
        "senses": _sense_rows(word_id),
        "external_links": links,
        "relations": _relation_rows(word_id, private_notes),
        "components": components,
        "occurs_in": occurs_in,
        "sources": sources,
        "sources_total": totals["n"],
        "source_page_count": totals["p"],
    }
