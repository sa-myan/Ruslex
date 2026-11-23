"""Reject malformed or ungrounded model output before staging."""
import re
from .prompts import *
from .taxonomy import TAG_SETS

def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def require_string(value, label, max_len=1000, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_len or not (value.strip() or allow_empty):
        raise ValueError(f"Invalid {label}")
    return value.strip()


def validate_senses(senses):
    if not isinstance(senses, list) or not 1 <= len(senses) <= 10:
        raise ValueError("Each entry must have 1–10 senses")
    for index, sense in enumerate(senses, start=1):
        meaning = require_string(sense.get("meaning"), "sense meaning", 180)
        description = require_string(sense.get("description", ""), "English description", 1000, True)
        if RUSSIAN.search(meaning) or not re.search(r"[A-Za-z]{2,}", meaning):
            raise ValueError(f"Sense {index} meaning must be an English gloss: {meaning[:90]!r}")
        # Russian headwords quoted in an otherwise English description are fine.
        # Do not accept a wholly Russian definition as an English description.
        if description and not re.search(r"[A-Za-z]{2,}", description):
            raise ValueError(f"Sense {index} description must be English prose: {description[:90]!r}")
        tags = sense.get("tags")
        if not isinstance(tags, dict) or set(tags) != set(TAG_SETS):
            raise ValueError("All three tag categories must be represented")
        for category, assigned in tags.items():
            if not isinstance(assigned, list) or len(set(assigned)) != len(assigned):
                raise ValueError("Duplicate or malformed assigned tags")
            if not set(assigned) <= TAG_SETS[category]:
                raise ValueError(f"Unknown {category} tags: {set(assigned) - TAG_SETS[category]}")
        patterns = sense.get("patterns")
        if not isinstance(patterns, list) or len(patterns) > 12:
            raise ValueError("Invalid patterns list")
        for pattern in patterns:
            require_string(pattern, "pattern", 160)
            if not RUSSIAN.search(pattern) or not CASE_END.search(pattern):
                raise ValueError("Pattern must use Cyrillic and end in a standard case: " + pattern)
        examples = sense.get("examples")
        if not isinstance(examples, list) or not 1 <= len(examples) <= 5:
            raise ValueError("Each sense needs 1–5 examples")
        for example in examples:
            ru = require_string(example.get("russian"), "Russian example", 350)
            translation = require_string(example.get("english"), "English example", 450)
            if not RUSSIAN.search(ru):
                raise ValueError("Russian example has no Cyrillic")
            if RUSSIAN.search(translation):
                raise ValueError("English example contains Cyrillic")


def validate_lexemes(response, requested):
    items = response.get("entries") if isinstance(response, dict) else None
    if not isinstance(items, list) or {e.get("id") for e in items} != set(requested) or \
            len(items) != len(requested):
        raise ValueError("Model response must cover every requested lexeme exactly once")
    for entry in items:
        pos = requested[entry["id"]]["pos"]
        aspect, animacy = entry.get("aspect"), entry.get("animacy")
        if aspect not in VALID_ASPECTS or animacy not in VALID_ANIMACIES:
            raise ValueError("Unrecognized aspect or animacy")
        if aspect is not None and pos not in {"VERB", "INFN"}:
            raise ValueError("Aspect on non-verb")
        if animacy is not None and pos != "NOUN":
            raise ValueError("Animacy on non-noun")
        try:
            validate_senses(entry.get("senses"))
        except ValueError as exc:
            raise ValueError(f"Lexeme {entry['id']} ({requested[entry['id']]['lemma']}): {exc}") from exc
        relations = entry.get("relations", [])
        if not isinstance(relations, list) or len(relations) > 20:
            raise ValueError("Malformed relations")
        for rel in relations:
            if rel.get("type") not in VALID_RELATIONS or rel.get("target_pos") not in VALID_POS:
                raise ValueError("Invalid relation")
            require_string(rel.get("target_lemma"), "relation target", 120)
            index = rel.get("source_sense_index")
            if index is not None and (not isinstance(index, int) or
                                      not 0 <= index < len(entry["senses"])):
                raise ValueError("Invalid relation sense index")
    return items


def validate_pages(response, requested):
    items = response.get("expressions") if isinstance(response, dict) else None
    if not isinstance(items, list):
        raise ValueError("Expression response must contain an expressions list")
    # Textbook grammar/reference pages can yield more established terms than
    # conversational pages. Limit output proportionally to pages in this batch.
    limit = min(100, max(35, 20 * len(requested)))
    if len(items) > limit:
        raise ValueError(f"Expression batch has {len(items)} entries; limit is {limit} "
                         f"for {len(requested)} source pages")
    for entry in items:
        try:
            lemma = require_string(entry.get("lemma"), "expression lemma", 120).lower()
            if not EXPRESSION.fullmatch(lemma) or entry.get("pos") not in VALID_POS:
                raise ValueError("Invalid expression lemma or POS")
            validate_senses(entry.get("senses"))
            components = entry.get("components")
            if not isinstance(components, list) or not 2 <= len(components) <= 12:
                raise ValueError("Expressions require ordered constituents")
            for comp in components:
                word = require_string(comp.get("lemma"), "component lemma", 100).lower()
                if not WORD.fullmatch(word) or comp.get("pos") not in VALID_POS:
                    raise ValueError("Invalid expression component")
                require_string(comp.get("surface"), "component surface", 100)
            attestations = entry.get("attestations")
            if not isinstance(attestations, list) or not attestations:
                raise ValueError("Each extracted expression must be attested")
            for att in attestations:
                page = requested.get(att.get("page_id"))
                surface = require_string(att.get("surface"), "attested surface", 150)
                if page is None or normalized(surface) not in normalized(page):
                    raise ValueError("Expression must actually occur on referenced page")
        except ValueError as exc:
            raise ValueError(f"Expression {entry.get('lemma', '?')!r}: {exc}") from exc
    return items

