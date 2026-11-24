"""Read-only access to the user's independently stored OpenRussian SQLite dump.

This module does not modify Ruslex or the OpenRussian database. The latter is a
reference dataset, not a second authoritative copy of Ruslex entries.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ACUTE = "\u0301"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
# Apostrophes are OpenRussian's stress markers when following a Russian vowel.
APOSTROPHE_STRESS = re.compile(rf"([{VOWELS}])['\u2019]")
PARTNER_SEPARATOR = re.compile(r"[;,]")
CYRILLIC_WORD = re.compile(r"^[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*$")
HYPHENS = str.maketrans({"‐": "-", "‑": "-", "–": "-"})


@dataclass(frozen=True)
class ReferenceWord:
    word_id: str
    bare: str
    accented_raw: str
    spelling: str
    stressed: str
    word_type: str
    rank: str
    level: str
    warnings: tuple[str, ...]


def plain_spelling(text: str) -> str:
    """Remove stress markup without collapsing ё into е."""
    return unicodedata.normalize("NFC", text.replace(ACUTE, "").replace("'", "").replace("\u2019", "").translate(HYPHENS)).strip()


def lookup_key(text: str) -> str:
    """Loose key for finding ё spellings; not a lexical identity key."""
    return plain_spelling(text).casefold().replace("ё", "е")


def match_capitalization(stressed: str, lemma: str) -> str:
    """Retain Ruslex case while preserving OpenRussian stress and ё locations."""
    source = plain_spelling(stressed)
    target = plain_spelling(lemma)
    if lookup_key(source) != lookup_key(target) or len(source) != len(target):
        raise ValueError("Headword spellings are not letter-aligned")
    result = []
    index = 0
    for char in stressed:
        if char == ACUTE:
            result.append(char)
        else:
            result.append(char.upper() if target[index].isupper() else char.lower()
                          if char.isalpha() else char)
            index += 1
    return "".join(result)


def normalize_accented(text: str) -> tuple[str, tuple[str, ...]]:
    """Convert OpenRussian apostrophe accents to combining U+0301.

    Always validate: malformed source values remain visible but are not trusted
    for automatic suggestions. NFC is applied before inserting acute marks.
    """
    source = unicodedata.normalize("NFC", text.strip().translate(HYPHENS))
    warnings: list[str] = []
    if any(c in source for c in ("'", "\u2019")):
        source = APOSTROPHE_STRESS.sub(lambda match: match.group(1) + ("" if match.group(1) in "ёЁ" else ACUTE), source)
    if "'" in source or "\u2019" in source:
        warnings.append("unrecognized apostrophe in stress source")
    if not CYRILLIC_WORD.fullmatch(plain_spelling(source)):
        warnings.append("non-Russian letters or unexpected characters")
    accent_count = source.count(ACUTE)
    yo_count = source.casefold().count("ё")
    if accent_count > 1 or yo_count > 1 or (accent_count and yo_count):
        warnings.append("multiple or conflicting stress markers")
    for index, char in enumerate(source):
        if char == ACUTE and (index == 0 or source[index - 1] not in VOWELS or source[index - 1] in "ёЁ"):
            warnings.append("accent mark does not follow an eligible vowel")
            break
    if not (accent_count or yo_count) and sum(char in VOWELS for char in source) > 1:
        warnings.append("no explicit stress on multisyllabic word")
    return source, tuple(warnings)


def _string(value: object) -> str:
    return "" if value is None else str(value)


def _word(row: sqlite3.Row) -> ReferenceWord:
    raw = _string(row["accented"]) or _string(row["bare"])
    stressed, warnings = normalize_accented(raw)
    spelling = plain_spelling(stressed)
    bare = _string(row["bare"])
    if lookup_key(bare) != lookup_key(spelling):
        warnings += ("bare and accented spellings do not agree",)
    return ReferenceWord(
        word_id=_string(row["id"]), bare=bare, accented_raw=raw,
        spelling=spelling, stressed=stressed,
        word_type=_string(row["type"]), rank=_string(row["rank"]),
        level=_string(row["level"]), warnings=warnings,
    )


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    # Only hardcoded table names are passed to PRAGMA, never external input.
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def verify_schema(db: sqlite3.Connection) -> dict[str, bool]:
    """Fail fast on an incompatible dump, while allowing optional tables."""
    required = {"id", "bare", "accented", "type", "rank", "level"}
    if missing := required - _columns(db, "words"):
        raise ValueError(f"Not a compatible OpenRussian dump: words is missing {', '.join(sorted(missing))}")
    optional = {
        "words_forms": {"word_id", "form", "form_type"},
        "translations": {"word_id", "lang", "tl"},
        "verbs": {"word_id", "aspect", "partner"},
    }
    present = {}
    for table, columns in optional.items():
        available = _columns(db, table)
        if available and not columns <= available:
            raise ValueError(f"OpenRussian {table} is missing columns: {', '.join(sorted(columns - available))}")
        present[table] = bool(available)
    return present


def reference_fingerprint(path: Path) -> str:
    """Identify the exact reference dump used when generating an audit."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def connect_reference(path: Path) -> Iterator[sqlite3.Connection]:
    """Connect explicitly read-only. Never create a missing SQLite file."""
    if not path.is_file():
        raise FileNotFoundError(f"OpenRussian SQLite dump not found: {path}")
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        verify_schema(db)
        yield db
    finally:
        db.close()


def word_rows(db: sqlite3.Connection) -> Iterator[ReferenceWord]:
    for row in db.execute(
        "SELECT id,bare,accented,type,rank,level FROM words ORDER BY id"
    ):
        yield _word(row)


def lookup(db: sqlite3.Connection, lemma: str) -> list[ReferenceWord]:
    """Read matching dictionary headwords, including spelling variants with ё."""
    key = lookup_key(lemma)
    if not key or not CYRILLIC_WORD.fullmatch(plain_spelling(lemma)):
        raise ValueError("Enter one Russian headword, using Cyrillic letters")
    # The name indexes old CSV dumps inconsistently: always match both fields
    # in Python rather than assuming a particular ё policy in words.bare.
    matches = [word for word in word_rows(db) if key in (lookup_key(word.bare), lookup_key(word.spelling))]
    return sorted(matches, key=lambda w: (w.spelling.casefold() != plain_spelling(lemma).casefold(), w.word_id))


def _related_data(db: sqlite3.Connection, word_id: str, include_forms: bool) -> dict:
    features = verify_schema(db)
    translations: list[str] = []
    if features["translations"]:
        translations = [_string(row[0]) for row in db.execute(
            "SELECT tl FROM translations WHERE word_id=? AND lang='en' ORDER BY rowid",
            (word_id,),
        ) if row[0]]
    verb_info = []
    if features["verbs"]:
        for row in db.execute("SELECT aspect,partner FROM verbs WHERE word_id=? ORDER BY rowid", (word_id,)):
            partner_names = [plain_spelling(part.strip()) for part in PARTNER_SEPARATOR.split(_string(row["partner"]))]
            verb_info.append({
                "aspect": _string(row["aspect"]),
                "partner_spellings": [p for p in partner_names if p],
            })
    forms = []
    if include_forms and features["words_forms"]:
        for row in db.execute("SELECT form_type,form FROM words_forms WHERE word_id=? ORDER BY form_type,form", (word_id,)):
            raw = _string(row["form"])
            stressed, warnings = normalize_accented(raw)
            forms.append({
                "form_type": _string(row["form_type"]),
                "spelling": plain_spelling(stressed),
                "stressed": stressed,
                "warnings": list(warnings),
            })
    return {"translations_en": translations, "verbs": verb_info, "forms": forms}


def result(word: ReferenceWord, db: sqlite3.Connection, *, include_forms: bool = False) -> dict:
    return {
        "id": word.word_id,
        "bare": word.bare,
        "spelling": word.spelling,
        "stressed": word.stressed,
        "raw_accented": word.accented_raw,
        "type": word.word_type,
        "rank": word.rank,
        "level": word.level,
        "warnings": list(word.warnings),
        **_related_data(db, word.word_id, include_forms),
    }


# A filter only when both dictionaries expose recognizable POS categories.
# OpenRussian dumps may use English or abbreviated types, so unknown types
# never silently eliminate candidates.
POS_TYPES = {
    "noun": "NOUN", "n": "NOUN", "substantive": "NOUN", "сущ": "NOUN",
    "verb": "VERB", "v": "VERB", "гл": "VERB",
    "adj": "ADJF", "adjective": "ADJF", "прилаг": "ADJF",
    "adv": "ADVB", "adverb": "ADVB", "нар": "ADVB",
    "pronoun": "NPRO", "pron": "NPRO", "мест": "NPRO",
    "number": "NUMR", "numeral": "NUMR", "числ": "NUMR",
    "prep": "PREP", "preposition": "PREP", "предл": "PREP",
    "conj": "CONJ", "conjunction": "CONJ", "союз": "CONJ",
    "particle": "PRCL", "part": "PRCL", "част": "PRCL",
    "interjection": "INTJ", "межд": "INTJ",
}


def pos_code(word_type: str) -> str | None:
    # A compound OpenRussian type like "noun, masculine" is recognized by
    # the first token. Unknown labels remain unresolved rather than guessed.
    first = re.split(r"[\s,;/()]+", word_type.casefold().strip())[0]
    return POS_TYPES.get(first)


def candidate_words(words: list[ReferenceWord], pos: str) -> tuple[list[ReferenceWord], bool]:
    """Filter only if every reference type is understood; otherwise abstain."""
    types = [pos_code(word.word_type) for word in words]
    if not words or any(code is None for code in types):
        return words, False
    # Ruslex uses pymorphy-style POS codes; normalize the safe equivalences.
    normalized_pos = {"INFN": "VERB", "ADJS": "ADJF", "COMP": "ADJF"}.get(pos, pos)
    compatible = [word for word, code in zip(words, types) if code == normalized_pos]
    return (compatible, True) if compatible else (words, False)
