"""Display conventional Cyrillic initialisms without changing stored lemma keys.

The SQLite schema predates abbreviation support and stores lowercased lemmas.
Keep lexicalized inflecting acronyms lowercased and preserve dotted spellings.
"""
import re

INITIALISM = re.compile(r"[а-яё]+(?:-[0-9]+)?")


def display(lemma: str, entry_type: str, stressed: str | None = None) -> str:
    value = stressed or lemma
    if entry_type != "abbreviation":
        return value
    if lemma in {"вуз", "загс"} or "." in lemma:
        return value
    # For initialisms the conventional written spelling is uppercase. The
    # underlying lemma remains lowercased for stable identity and search.
    if INITIALISM.fullmatch(value) and value == value.lower():
        return value.upper()
    return value
