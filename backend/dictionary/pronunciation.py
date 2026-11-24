"""Public pronunciation readers and permission-gated manual editing.

The lexeme spelling remains the stable identity. Readable pronunciations are
independent records. Optional sense links prevent guessing homograph meaning.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from django.db import connections, transaction

from .query_helpers import LEXICON, _batches, _sql_placeholders, legacy_rows

ACUTE = "\u0301"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
FIELDS = ("id", "lexeme_id", "stressed", "source", "reference_id",
          "reference_fingerprint", "verification", "is_primary", "created_at")


def installed() -> bool:
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='lexeme_pronunciations'"
        )
        return cursor.fetchone() is not None


def pronunciations_for(word_ids: list[int]) -> dict[int, list[dict]]:
    if not word_ids or not installed():
        return {}
    grouped = defaultdict(list)
    for batch in _batches(list(dict.fromkeys(word_ids))):
        rows = legacy_rows(
            f"""SELECT {','.join(FIELDS)} FROM lexeme_pronunciations
                WHERE lexeme_id IN ({_sql_placeholders(len(batch))})
                ORDER BY is_primary DESC, id""", batch,
        )
        for row in rows:
            row["is_primary"] = bool(row["is_primary"])
            grouped[row["lexeme_id"]].append(row)
    return dict(grouped)


def display_lemma(lemma: str, rows: list[dict]) -> str:
    expected = lemma.replace(ACUTE, "").casefold().replace("ё", "е")
    primary = [row for row in rows if row["is_primary"]
               and row["verification"] != "disputed"
               and row["stressed"].replace(ACUTE, "").casefold().replace("ё", "е") == expected]
    return primary[0]["stressed"] if len(primary) == 1 else lemma


def normalize_stressed(value: object, lemma: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Stressed spelling must be text")
    value = unicodedata.normalize("NFC", value.strip())
    if not value or len(value) > 150:
        raise ValueError("Invalid stressed spelling length")
    source = unicodedata.normalize("NFC", lemma)
    # Ё may be restored without changing lexical identity.
    plain = value.replace(ACUTE, "").casefold().replace("ё", "е")
    expected = source.replace(ACUTE, "").casefold().replace("ё", "е")
    if plain != expected:
        raise ValueError("Pronunciation must match the lemma, except for е/ё")
    marks = [index for index, char in enumerate(value) if char == ACUTE]
    if len(marks) > 1:
        raise ValueError("Only one primary stress marker is supported")
    if marks and (marks[0] == 0 or value[marks[0]-1] not in VOWELS
                  or value[marks[0]-1] in "ёЁ"):
        raise ValueError("Put the accent after a non-ё vowel")
    letters = [char for char in value if char in VOWELS]
    if not letters or any(char not in VOWELS + ACUTE + "- " and not char.isalpha() for char in value):
        raise ValueError("Unexpected characters in stressed spelling")
    if any(char.isalpha() and char not in
           "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
           for char in value):
        raise ValueError("Stressed spelling must use Russian letters")
    if len(letters) > 1 and not marks and value.casefold().count("ё") != 1:
        raise ValueError("Multisyllabic words need one marked stress or a single ё")
    if marks and "ё" in value.casefold():
        raise ValueError("Multiple stressed vowels (ё and acute)")
    return value


@transaction.atomic(using=LEXICON)
def save(word_id: int, data: dict, record_id: int | None = None) -> dict:
    from .services import word
    entry = word(word_id)
    if not installed():
        raise ValueError("Pronunciation schema not installed; run the stress migration")
    allowed = {"stressed", "is_primary", "sense_ids"}
    if not isinstance(data, dict) or not data or set(data) - allowed:
        raise ValueError("Unknown pronunciation fields")
    stressed = normalize_stressed(data.get("stressed"), entry.lemma)
    primary = data.get("is_primary", True)
    if type(primary) is not bool:
        raise ValueError("is_primary must be boolean")
    sense_ids = data.get("sense_ids", [])
    if not isinstance(sense_ids, list) or any(type(x) is not int or x < 1 for x in sense_ids):
        raise ValueError("sense_ids must be an array of positive integers")
    if len(sense_ids) != len(set(sense_ids)):
        raise ValueError("Duplicate sense IDs")
    with connections[LEXICON].cursor() as cursor:
        for sid in sense_ids:
            cursor.execute("SELECT 1 FROM senses WHERE id=%s AND lexeme_id=%s", [sid, word_id])
            if cursor.fetchone() is None:
                raise ValueError("Sense does not belong to this entry")
        if record_id is not None:
            cursor.execute(
                "SELECT 1 FROM lexeme_pronunciations WHERE id=%s AND lexeme_id=%s",
                [record_id, word_id],
            )
            if cursor.fetchone() is None:
                raise LookupError("Pronunciation does not belong to this entry")
        if primary:
            cursor.execute("UPDATE lexeme_pronunciations SET is_primary=0 WHERE lexeme_id=%s",
                           [word_id])
        if record_id is None:
            cursor.execute(
                """INSERT INTO lexeme_pronunciations
                   (lexeme_id, stressed, source, reference_id,
                    reference_fingerprint, verification, is_primary, created_at)
                   VALUES (%s,%s,'manual','','','verified',%s,%s)""",
                [word_id, stressed, int(primary), datetime.now(timezone.utc).isoformat()],
            )
            record_id = cursor.lastrowid
        else:
            cursor.execute(
                """UPDATE lexeme_pronunciations
                   SET stressed=%s, source='manual',reference_id='',
                       reference_fingerprint='',verification='verified',is_primary=%s
                   WHERE id=%s AND lexeme_id=%s""",
                [stressed, int(primary), record_id, word_id],
            )
        cursor.execute("DELETE FROM sense_pronunciations WHERE pronunciation_id=%s", [record_id])
        for sid in sense_ids:
            cursor.execute(
                "INSERT INTO sense_pronunciations(sense_id,pronunciation_id) VALUES (%s,%s)",
                [sid, record_id],
            )
    return {"id": record_id, "stressed": stressed, "is_primary": primary,
            "sense_ids": sense_ids, "verification": "verified"}


@transaction.atomic(using=LEXICON)
def remove(word_id: int, record_id: int) -> dict:
    from .services import word
    word(word_id)
    if not installed():
        raise LookupError("No pronunciation records")
    with connections[LEXICON].cursor() as cursor:
        cursor.execute(
            "DELETE FROM lexeme_pronunciations WHERE id=%s AND lexeme_id=%s",
            [record_id, word_id],
        )
        if not cursor.rowcount:
            raise LookupError("Pronunciation does not belong to this entry")
    return {"removed": True}


def sense_ids_for(pronunciation_ids: list[int]) -> dict[int, list[int]]:
    if not pronunciation_ids or not installed():
        return {}
    grouped = defaultdict(list)
    for batch in _batches(pronunciation_ids):
        for row in legacy_rows(
            f"""SELECT pronunciation_id,sense_id FROM sense_pronunciations
                WHERE pronunciation_id IN ({_sql_placeholders(len(batch))})
                ORDER BY sense_id""", batch,
        ):
            grouped[row["pronunciation_id"]].append(row["sense_id"])
    return dict(grouped)
