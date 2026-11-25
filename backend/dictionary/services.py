"""Database mutations for the existing lexicon schema.

Each public operation has its own transaction on the ``lexicon`` connection.
Never write dictionary tables through Django's default (accounts) database.
Input validation lives in ``validation.py``; these functions enforce data
relationships and return the API's established response shapes.
"""

from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from . import models
from .catalog import RELATIONS, STATUSES, SYMMETRIC, TAG_CATEGORIES
from .validation import (
    BadRequest,
    external_url,
    fail,
    fields,
    identifier,
    identity,
    string,
)


LEXICON = "lexicon"
RECORD_MODELS = {
    "senses": models.Sense,
    "examples": models.Example,
    "patterns": models.Pattern,
}
RECORD_FIELDS = {
    "senses": ("meaning", "description"),
    "examples": ("russian", "english"),
    "patterns": ("pattern",),
}
IDENTITY_FIELDS = {"lemma", "pos", "entry_type", "aspect", "animacy"}
EDITABLE_WORD_FIELDS = IDENTITY_FIELDS | {"human_status", "notes"}

# Keep the historical names available to callers which import these constants.
TABLE = RECORD_MODELS
ALLOWED = RECORD_FIELDS


def word(word_id: int) -> models.Lexeme:
    entry = models.Lexeme.objects.using(LEXICON).filter(pk=word_id).first()
    if entry is None:
        raise LookupError("Entry not found")
    return entry


def sense(word_id: int, sense_id: int, active: bool = False) -> models.Sense:
    matches = models.Sense.objects.using(LEXICON).filter(
        pk=sense_id, lexeme_id=word_id
    )
    if active:
        matches = matches.filter(active=1)

    result = matches.first()
    if result is None:
        raise LookupError("Sense not found under this entry")
    return result


def _check_entry_type_change(entry: models.Lexeme, values: dict) -> None:
    if values["entry_type"] == entry.entry_type:
        return

    components = models.ExpressionComponent.objects.using(LEXICON)
    if values["entry_type"] != "expression":
        if components.filter(expression_id=entry.id).exists():
            fail("Remove constituents before converting expression into a word")
    elif components.filter(word_id=entry.id).exists():
        fail("A word used by an expression cannot be converted")


def _check_aspect_links(entry: models.Lexeme, values: dict) -> None:
    relations = models.Relation.objects.using(LEXICON).filter(
        Q(source_lexeme_id=entry.id) | Q(target_lexeme_id=entry.id)
    )
    aspect_links = [rel for rel in relations if rel.relation_type == "aspect_pair"]

    if aspect_links and values["pos"] not in {"VERB", "INFN"}:
        fail("Remove aspect links before changing this verb's part of speech")

    for relation in aspect_links:
        other_id = (
            relation.target_lexeme_id
            if relation.source_lexeme_id == entry.id
            else relation.source_lexeme_id
        )
        other = word(other_id)
        if (
            values["aspect"] not in {"perfective", "imperfective"}
            or {values["aspect"], other.aspect} != {"perfective", "imperfective"}
        ):
            fail("New aspect conflicts with an aspect pair")


@transaction.atomic(using=LEXICON)
def create_word(data: dict) -> dict:
    values = identity(data)
    existing = models.Lexeme.objects.using(LEXICON).filter(
        lemma=values["lemma"], pos=values["pos"]
    ).first()

    if existing is not None:
        if existing.entry_type != values["entry_type"]:
            fail("Entry already exists with a different type")
        return {"id": existing.id, "lemma": existing.lemma, "pos": existing.pos}

    entry = models.Lexeme.objects.using(LEXICON).create(
        **values,
        human_status="unreviewed",
        notes="",
        created_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return {"id": entry.id, "lemma": entry.lemma, "pos": entry.pos}


@transaction.atomic(using=LEXICON)
def update_word(word_id: int, data: dict) -> dict:
    entry = word(word_id)
    fields(data, EDITABLE_WORD_FIELDS)
    if not data:
        fail("Nothing to update")

    if IDENTITY_FIELDS.intersection(data):
        values = identity(data, entry)
        _check_entry_type_change(entry, values)
        _check_aspect_links(entry, values)
        for name, value in values.items():
            setattr(entry, name, value)

    if "human_status" in data:
        if not isinstance(data["human_status"], str) or data["human_status"] not in STATUSES:
            fail("Invalid review status")
        entry.human_status = data["human_status"]

    if "notes" in data:
        notes = string(data, "notes", required=False, maxlen=5000)
        if notes is None:
            fail("Notes cannot be null")
        entry.notes = notes

    entry.save(using=LEXICON)
    return {
        "id": entry.id,
        "lemma": entry.lemma,
        "pos": entry.pos,
        "human_status": entry.human_status,
        "entry_type": entry.entry_type,
        "aspect": entry.aspect,
        "animacy": entry.animacy,
        "notes": entry.notes,
    }


def _record_parent(word_id: int, table: str, sense_id: int | None) -> dict:
    if table == "senses":
        return {"lexeme_id": word_id}
    if sense_id is None:
        fail("Parent sense required")
    sense(word_id, sense_id, active=True)
    return {"sense_id": sense_id}


@transaction.atomic(using=LEXICON)
def save_record(
    word_id: int,
    table: str,
    data: dict,
    *,
    record_id: int | None = None,
    sense_id: int | None = None,
) -> dict:
    word(word_id)
    if table not in RECORD_MODELS:
        fail("Unknown record type")

    columns = RECORD_FIELDS[table]
    fields(data, columns)
    values = {
        column: string(data, column, required=index == 0) or ""
        for index, column in enumerate(columns)
    }
    parent = _record_parent(word_id, table, sense_id)
    records = RECORD_MODELS[table].objects.using(LEXICON)

    if record_id is None:
        record = records.create(**parent, **values)
    else:
        record = records.filter(pk=record_id, **parent).first()
        if record is None:
            raise LookupError("Record not found under this sense")
        for name, value in values.items():
            setattr(record, name, value)
        record.save(using=LEXICON)

    return {"id": record.id, **parent, **values, "active": record.active}


@transaction.atomic(using=LEXICON)
def set_active(word_id: int, table: str, record_id: int, active: bool) -> dict:
    if table not in RECORD_MODELS:
        fail("Invalid record type")
    if type(active) is not bool:
        fail("active must be boolean")
    word(word_id)

    records = RECORD_MODELS[table].objects.using(LEXICON)
    if table == "senses":
        records = records.filter(lexeme_id=word_id)
    else:
        sense_ids = models.Sense.objects.using(LEXICON).filter(
            lexeme_id=word_id
        ).values("id")
        records = records.filter(sense_id__in=sense_ids)

    if not records.filter(pk=record_id).update(active=int(active)):
        raise LookupError("Record not found under this entry")
    return {"id": record_id, "active": int(active)}


@transaction.atomic(using=LEXICON)
def attach_tag(word_id: int, sense_id: int, data: dict) -> dict:
    sense(word_id, sense_id)
    fields(data, {"name", "category"})
    category = string(data, "category", maxlen=30)
    if category not in TAG_CATEGORIES:
        fail("Invalid tag category")
    name = string(data, "name", maxlen=48).casefold()

    tag, _ = models.Tag.objects.using(LEXICON).get_or_create(
        name=name, category=category
    )
    # sense_tags is a legacy composite-key table, not a managed Django model.
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            "INSERT OR IGNORE INTO sense_tags(sense_id,tag_id) VALUES(%s,%s)",
            [sense_id, tag.id],
        )
    return {"id": tag.id, "name": tag.name, "category": tag.category}


@transaction.atomic(using=LEXICON)
def detach_tag(word_id: int, sense_id: int, tag_id: int) -> dict:
    sense(word_id, sense_id)
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            "DELETE FROM sense_tags WHERE sense_id=%s AND tag_id=%s",
            [sense_id, tag_id],
        )
        if not cursor.rowcount:
            raise LookupError("Tag not attached to this sense")
    return {"removed": True}


def _relation_endpoints(
    word_id: int,
    other_id: int,
    own_sense_id: int | None,
    other_sense_id: int | None,
    kind: str,
    previous: models.Relation | None,
) -> tuple[int, int, int | None, int | None]:
    """Preserve the direction of edits to an incoming derivation relation.

    Symmetric relations, including aspect pairs, use ascending lexeme IDs.
    Do not arbitrarily reverse a directional derivation during editing.
    """
    source, target = word_id, other_id
    if (
        previous is not None
        and previous.relation_type == "derivation"
        and kind == "derivation"
        and previous.target_lexeme_id == word_id
    ):
        source, target = target, source
        own_sense_id, other_sense_id = other_sense_id, own_sense_id

    if kind in SYMMETRIC and source > target:
        source, target = target, source
        own_sense_id, other_sense_id = other_sense_id, own_sense_id

    return source, target, own_sense_id, other_sense_id


@transaction.atomic(using=LEXICON)
def save_relation(word_id: int, data: dict, relation_id: int | None = None) -> dict:
    fields(
        data,
        {"target_lexeme_id", "relation_type", "source_sense_id", "target_sense_id", "notes"},
    )
    own = word(word_id)
    other = word(identifier(data, "target_lexeme_id"))
    if own.id == other.id:
        fail("Cannot link an entry to itself")

    kind = string(data, "relation_type", maxlen=20)
    if kind not in RELATIONS:
        fail("Unknown relationship type")
    if kind == "aspect_pair" and not (
        own.pos in {"VERB", "INFN"}
        and other.pos in {"VERB", "INFN"}
        and {own.aspect, other.aspect} == {"perfective", "imperfective"}
    ):
        fail("Aspect pairs require verbs with opposite known aspects")

    own_sense = identifier(data, "source_sense_id", nullable=True)
    other_sense = identifier(data, "target_sense_id", nullable=True)
    if own_sense:
        sense(word_id, own_sense)
    if other_sense:
        sense(other.id, other_sense)

    old = None
    if relation_id is not None:
        old = models.Relation.objects.using(LEXICON).filter(pk=relation_id).first()
        if old is None or word_id not in (old.source_lexeme_id, old.target_lexeme_id):
            raise LookupError("Relationship not attached to this entry")

    source, target, source_sense, target_sense = _relation_endpoints(
        word_id, other.id, own_sense, other_sense, kind, old
    )
    values = {
        "source_lexeme_id": source,
        "target_lexeme_id": target,
        "relation_type": kind,
        "source_sense_id": source_sense,
        "target_sense_id": target_sense,
        "notes": string(data, "notes", required=False, maxlen=3000) or "",
    }
    if old is None:
        relation = models.Relation.objects.using(LEXICON).create(**values)
    else:
        for name, value in values.items():
            setattr(old, name, value)
        old.save(using=LEXICON)
        relation = old

    return {"id": relation.id, **values}


@transaction.atomic(using=LEXICON)
def remove_relation(word_id: int, relation_id: int) -> dict:
    relation = models.Relation.objects.using(LEXICON).filter(pk=relation_id).first()
    if relation is None or word_id not in (
        relation.source_lexeme_id,
        relation.target_lexeme_id,
    ):
        raise LookupError("Relation not found under this entry")
    relation.delete(using=LEXICON)
    return {"removed": True}


@transaction.atomic(using=LEXICON)
def save_component(word_id: int, data: dict, component_id: int | None = None) -> dict:
    fields(data, {"word_id", "position", "surface", "notes"})
    expression = word(word_id)
    target = word(identifier(data, "word_id"))
    if expression.entry_type != "expression" or target.entry_type != "word":
        fail("An expression can only contain word entries")

    values = {
        "expression_id": word_id,
        "word_id": target.id,
        "position": identifier(data, "position"),
        "surface": string(data, "surface", required=False, maxlen=120) or "",
        "notes": string(data, "notes", required=False, maxlen=3000) or "",
    }
    records = models.ExpressionComponent.objects.using(LEXICON)
    if component_id is None:
        component = records.create(**values)
    else:
        component = records.filter(pk=component_id, expression_id=word_id).first()
        if component is None:
            raise LookupError("Constituent not attached to this expression")
        for name, value in values.items():
            setattr(component, name, value)
        component.save(using=LEXICON)

    return {"id": component.id, **values}


@transaction.atomic(using=LEXICON)
def remove_component(word_id: int, component_id: int) -> dict:
    component = models.ExpressionComponent.objects.using(LEXICON).filter(
        pk=component_id, expression_id=word_id
    ).first()
    if component is None:
        raise LookupError("Constituent not attached to this expression")
    component.delete(using=LEXICON)
    return {"removed": True}


@transaction.atomic(using=LEXICON)
def save_external_link(word_id: int, data: dict, link_id: int | None = None) -> dict:
    word(word_id)
    fields(data, {"label", "url"})
    values = {
        "label": string(data, "label", maxlen=80),
        "url": external_url(data),
    }
    records = models.ExternalLink.objects.using(LEXICON)
    if link_id is None:
        link = records.create(lexeme_id=word_id, **values)
    else:
        link = records.filter(pk=link_id, lexeme_id=word_id).first()
        if link is None:
            raise LookupError("Link not attached to entry")
        for name, value in values.items():
            setattr(link, name, value)
        link.save(using=LEXICON)

    return {"id": link.id, "lexeme_id": word_id, **values}


@transaction.atomic(using=LEXICON)
def remove_external_link(word_id: int, link_id: int) -> dict:
    link = models.ExternalLink.objects.using(LEXICON).filter(
        pk=link_id, lexeme_id=word_id
    ).first()
    if link is None:
        raise LookupError("Link not attached to entry")
    link.delete(using=LEXICON)
    return {"removed": True}
