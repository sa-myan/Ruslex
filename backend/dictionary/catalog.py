"""Small closed vocabularies; keep lexical tag taxonomy in the lexicon DB."""
PARTS_OF_SPEECH = [
    ("NOUN", "Noun"), ("VERB", "Verb"), ("INFN", "Infinitive"),
    ("ADJF", "Adjective (full)"), ("ADJS", "Adjective (short)"),
    ("COMP", "Comparative"), ("ADVB", "Adverb"), ("NPRO", "Pronoun"),
    ("PRON", "Pronoun (legacy)"), ("NUMR", "Numeral"),
    ("PRED", "Predicative"), ("PREP", "Preposition"), ("CONJ", "Conjunction"),
    ("PRCL", "Particle"), ("INTJ", "Interjection"), ("PRTF", "Participle (full)"),
    ("PRTS", "Participle (short)"), ("GRND", "Gerund"),
    ("UNKN", "Unclassified"), ("OTHER", "Other"),
]
POS = {x for x, _ in PARTS_OF_SPEECH}
STATUSES = {"unreviewed", "kept", "followup", "hidden"}
ASPECTS = {"imperfective", "perfective", "biaspectual"}
ANIMACIES = {"animate", "inanimate", "variable"}
RELATIONS = {"aspect_pair", "synonym", "antonym", "derivation", "related"}
SYMMETRIC = {"aspect_pair", "synonym", "antonym", "related"}
TAG_CATEGORIES = {"semantic", "grammatical", "usage"}
