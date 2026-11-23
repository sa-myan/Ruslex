"""Conservative sense-level learner taxonomy used by the enrichment pipeline.

Tags are optional and non-exclusive within each category. The taxonomy is
versioned here to avoid uncontrolled LLM-created classifications.
"""

TAXONOMY_VERSION = 1

TAG_GROUPS = {
    "grammatical": (
        "countable uncountable collective-noun singular-only plural-only "
        "indeclinable common-gender substantivized-adjective transitive "
        "intransitive impersonal light-verb motion-unidirectional "
        "motion-multidirectional qualitative-adjective relative-adjective "
        "possessive-adjective short-form-only no-short-form numeral-cardinal "
        "numeral-ordinal numeral-collective numeral-fractional numeral-indefinite "
        "personal-pronoun reflexive-pronoun possessive-pronoun "
        "demonstrative-pronoun interrogative-pronoun relative-pronoun "
        "indefinite-pronoun negative-pronoun determinative-pronoun "
        "coordinating-conjunction subordinating-conjunction negative-particle "
        "interrogative-particle focus-particle modal-particle "
        "intensifying-particle"
    ).split(),
    "semantic": (
        "people relationships emotions body health food home clothing shopping "
        "money work education communication time space movement transport "
        "travel leisure sports nature weather animals plants environment "
        "geography materials agriculture society culture religion law "
        "government politics economics business media art history military "
        "safety science mathematics medicine language technology computing "
        "engineering construction industry energy"
    ).split(),
    "usage": (
        "colloquial formal literary poetic slang professional-jargon "
        "bureaucratic academic technical-register journalistic vulgar "
        "offensive regional archaic dated historical rare ironic humorous "
        "affectionate derogatory euphemistic figurative idiom collocation "
        "formulaic-expression proverb multiword-term discourse-marker filler"
    ).split(),
}

TAG_SETS = {category: frozenset(names) for category, names in TAG_GROUPS.items()}


def seed_tags(db):
    """Install approved tag names without assigning them to any sense."""
    for category, names in TAG_GROUPS.items():
        db.executemany(
            "INSERT OR IGNORE INTO tags(category,name) VALUES(?,?)",
            ((category, name) for name in names),
        )
