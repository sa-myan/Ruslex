"""Pure Unicode-aware search relevance, independent of Django and SQLite.

English word boundaries matter: searching ``read`` must not match ``bread``.
Keep these tiers stable because saved v3 search fixtures depend on the order.
"""

import re
import unicodedata


def folded(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    letters = "".join(
        character for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return letters.casefold().replace("ё", "е")


def english_quality(text: str, query: str) -> int:
    if not query:
        return 0

    value = folded(text)
    escaped = re.escape(query)
    if re.search(r"(?<!\w)" + escaped + r"(?!\w)", value):
        return 2
    return 1 if re.search(r"(?<!\w)" + escaped, value) else 0


def score(lemma: str, senses, query: str, *, english: bool) -> int | None:
    """Return relevance tier 0–5, or None if the entry does not match.

    Each sense needs ``meaning`` and ``description`` string attributes.
    """
    value = folded(lemma)
    if value == query:
        return 0
    if value.startswith(query):
        return 1
    if query in value:
        return 2

    if english:
        if any(english_quality(item.meaning, query) == 2 for item in senses):
            return 3
        if any(english_quality(item.meaning, query) == 1 for item in senses):
            return 4
        if any(english_quality(item.description, query) == 2 for item in senses):
            return 5
        return None

    if any(
        query in folded(item.meaning) or query in folded(item.description)
        for item in senses
    ):
        return 3
    return None
