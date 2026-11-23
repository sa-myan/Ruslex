"""Pure Unicode-aware relevance scoring, independent of Django and SQLite.

This is intentionally testable without a web server. Never match an English
search string inside another word: 'read' must not match 'bread'.
"""
import re
import unicodedata


def folded(text):
    value = unicodedata.normalize("NFD", str(text or ""))
    return "".join(x for x in value if unicodedata.category(x) != "Mn").casefold().replace("ё", "е")


def english_quality(text, query):
    if not query:
        return 0
    value = folded(text)
    term = re.escape(query)
    if re.search(r"(?<!\w)" + term + r"(?!\w)", value):
        return 2
    return 1 if re.search(r"(?<!\w)" + term, value) else 0


def score(lemma, senses, query, *, english):
    """Return relevance tier (0–5) or None if there is no match.

    A sense is any object with .meaning and .description attributes.
    """
    lemma=folded(lemma)
    if lemma==query: return 0
    if lemma.startswith(query):return 1
    if query in lemma:return 2
    if english:
        if any(english_quality(s.meaning,query)==2 for s in senses):return 3
        if any(english_quality(s.meaning,query)==1 for s in senses):return 4
        if any(english_quality(s.description,query)==2 for s in senses):return 5
        return None
    if any(query in folded(s.meaning) or query in folded(s.description) for s in senses):return 3
    return None
