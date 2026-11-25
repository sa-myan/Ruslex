"""Pure validation of dictionary-editing payloads.

This module deliberately has no Django dependency. It can be tested quickly
without opening either SQLite database or starting the application.
"""

import re
import unicodedata
from urllib.parse import urlsplit

from .catalog import ANIMACIES, ASPECTS, POS


class BadRequest(ValueError):
    """Invalid input supplied by an API client (HTTP 400)."""


def fail(message: str) -> None:
    raise BadRequest(message)


def fields(data: object, allowed: set[str] | tuple[str, ...]) -> dict:
    """Reject unexpected fields instead of silently ignoring client mistakes."""
    if not isinstance(data, dict) or set(data) - set(allowed):
        fail("Unknown or malformed fields")
    return data


def string(
    data: dict, key: str, *, required: bool = True, maxlen: int = 3000
) -> str | None:
    value = data.get(key)
    if value is None:
        if required:
            fail(f"{key} is required")
        return None

    if (
        not isinstance(value, str)
        or (required and not value.strip())
        or len(value) > maxlen
    ):
        fail(f"Invalid {key}")
    return value.strip()


def identifier(data: dict, key: str, *, nullable: bool = False) -> int | None:
    value = data.get(key)
    if nullable and value in (None, ""):
        return None

    # bool is a subclass of int; it must not be accepted as a database ID.
    if type(value) is not int or value <= 0:
        fail(f"Invalid {key}")
    return value


WORD_PATTERN = re.compile(r"[а-яё]+(?:[-‑][а-яё]+)*")
EXPRESSION_PATTERN = re.compile(
    r"[а-яё]+(?:[-‑][а-яё]+)*(?:[ ,]+[а-яё]+(?:[-‑][а-яё]+)*)+[.!?]?"
)
ENTRY_FIELDS = {"lemma", "pos", "entry_type", "aspect", "animacy", "human_status", "notes"}


def identity(data: dict, current=None) -> dict:
    """Return normalized entry identity, preserving the existing Russian rules.

    ``current`` is a Lexeme-like object used for partial updates. This function
    does not read or write the database.
    """
    fields(data, ENTRY_FIELDS)

    kind = data.get("entry_type", current.entry_type if current else "word")
    lemma = data.get("lemma", current.lemma if current else None)
    pos = data.get("pos", current.pos if current else None)

    if not isinstance(kind, str) or kind not in {"word", "expression", "abbreviation"}:
        fail("Invalid entry type")
    if not isinstance(lemma, str):
        fail("Lemma required")

    lemma = " ".join(lemma.split()).strip()
    lemma = unicodedata.normalize("NFC", lemma).replace("\u0301", "").casefold()
    pattern = WORD_PATTERN if kind != "expression" else EXPRESSION_PATTERN
    if not pattern.fullmatch(lemma) or len(lemma) > 120:
        fail("Enter a Russian word, or a multiword Russian expression")

    if not isinstance(pos, str) or pos not in POS:
        fail("Invalid part of speech")

    aspect = data.get("aspect", current.aspect if current else None)
    animacy = data.get("animacy", current.animacy if current else None)

    if pos not in {"VERB", "INFN"} and "aspect" not in data:
        aspect = None
    if pos != "NOUN" and "animacy" not in data:
        animacy = None

    if aspect is not None and (
        not isinstance(aspect, str)
        or aspect not in ASPECTS
        or pos not in {"VERB", "INFN"}
    ):
        fail("Only verbs and infinitives can have a valid aspect")
    if animacy is not None and (
        not isinstance(animacy, str)
        or animacy not in ANIMACIES
        or pos != "NOUN"
    ):
        fail("Only nouns can have animacy")

    return {
        "lemma": lemma,
        "pos": pos,
        "entry_type": kind,
        "aspect": aspect,
        "animacy": animacy,
    }


def external_url(data: dict, key: str = "url") -> str:
    """Accept absolute HTTP(S) links without credentials or control chars."""
    url = string(data, key, maxlen=2048)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        fail("URL cannot contain spaces or controls")

    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError
        # Accessing .port also rejects malformed numbers and out-of-range ports.
        _ = parsed.port
    except ValueError:
        fail("Only absolute HTTP(S) URLs without credentials are allowed")
    return url
