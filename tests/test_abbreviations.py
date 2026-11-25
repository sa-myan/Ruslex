"""Abbreviations are lexical entry types, not parts of speech.

All tests use copied synthetic dictionaries. No live data is changed.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from processing.abbreviations import (
    initialize, categorize, plan, rehearse, supports_abbreviations,
)
from processing.forms import apply_decisions
from processing.ocr import parse_forms, tokenize

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class FakeMorph:
    def parse(self, surface):
        if surface == "мгу":
            return []
        return [
            SimpleNamespace(normal_form=surface,
                            tag=SimpleNamespace(POS="NOUN"),
                            is_known=True),
        ]


class AbbreviationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live = self.root / "lexicon.db"
        self.backups = self.root / "backups"
        with sqlite3.connect(self.live) as db:
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            db.executescript("""
                INSERT INTO lexemes(id,lemma,pos,human_status)
                VALUES (1,'мгу','NOUN','kept'),
                       (2,'вуз','NOUN','kept'),
                       (3,'стол','NOUN','kept'),
                       (4,'фсб','NOUN','hidden'),
                       (5,'пример','NOUN','kept');
                INSERT INTO senses(id,lexeme_id,meaning)
                VALUES(10,1,'Moscow State University'),
                      (11,2,'higher education institution'),
                      (12,3,'table'),
                      (13,4,'Federal Security Service'),
                      (14,5,'an abbreviation of something');
                INSERT INTO books(id,title,edition) VALUES(1,'Practice','');
                INSERT INTO pages(id,book_id,pdf_page,printed_page,markdown,source)
                  VALUES(1,1,1,1,'МГУ и вуз','fixture');
                INSERT INTO lexeme_pages(lexeme_id,page_id,surface,context,count)
                  VALUES(1,1,'мгу','МГУ и вуз',1);
            """)

    def test_migration_preserves_rows_links_and_constraints(self):
        with sqlite3.connect(self.live) as db:
            before = db.execute("SELECT * FROM lexemes ORDER BY id").fetchall()
            self.assertRaises(sqlite3.IntegrityError, db.execute,
                              "INSERT INTO lexemes(lemma,pos,entry_type) VALUES('тест','NOUN','abbreviation')")
            db.rollback()
        migrated = initialize(self.live, self.backups)
        self.assertTrue(migrated["changed"])
        self.assertTrue(list(self.backups.glob("before-stress-abbreviation-schema-*.db")))
        self.assertFalse(initialize(self.live, self.backups)["changed"])
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute("SELECT * FROM lexemes ORDER BY id").fetchall(), before)
            self.assertEqual(db.execute("SELECT lexeme_id FROM senses WHERE id=10").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT lexeme_id FROM lexeme_pages WHERE page_id=1").fetchone()[0], 1)
            db.execute(
                "INSERT INTO lexemes(lemma,pos,entry_type) VALUES('ржд','NOUN','abbreviation')"
            )
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_classification_is_repeatable_and_hidden_excluded(self):
        before = self.live.read_bytes()
        preview = plan(self.live)
        self.assertFalse(preview["schema_ready"])
        self.assertEqual([r["lemma"] for r in preview["automatic_candidates"]],
                         ["мгу", "вуз"])
        self.assertEqual([r["lemma"] for r in preview["review_candidates"]],
                         ["пример"])
        self.assertEqual(before, self.live.read_bytes())
        initialize(self.live, self.backups)
        outcome = categorize(self.live, self.backups)
        self.assertEqual(outcome["reclassified"], 2)
        self.assertEqual(categorize(self.live, self.backups)["reclassified"], 0)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute(
                "SELECT entry_type FROM lexemes WHERE id=1"
            ).fetchone()[0], "abbreviation")
            self.assertEqual(db.execute(
                "SELECT entry_type FROM lexemes WHERE id=4"
            ).fetchone()[0], "word")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM senses"
            ).fetchone()[0], 5)

    def test_ocr_offers_known_or_uppercase_abbreviations_to_ai(self):
        known = parse_forms("мгу", FakeMorph())
        self.assertEqual(known[0]["entry_type"], "abbreviation")
        unfamiliar = parse_forms("юнфп", FakeMorph(), uppercase_hint=True)
        self.assertTrue(any(x["entry_type"] == "abbreviation" for x in unfamiliar))
        ordinary = parse_forms("дом", FakeMorph())
        self.assertFalse(any(x["entry_type"] == "abbreviation" for x in ordinary))

    def test_ai_can_admit_abbreviation_without_changing_existing_entry(self):
        initialize(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            db.row_factory = sqlite3.Row
            db.execute("INSERT INTO reviews(id,book_id,surface) VALUES(2,1,'ржд')")
            analysis = [{"lemma": "ржд", "pos": "NOUN",
                         "entry_type": "abbreviation", "known": True}]
            batch = [{"id": 2, "surface": "ржд", "analyses": analysis}]
            proposal = {"results": [{
                "id": 2, "decision": "admit", "confidence": "high",
                "entries": [{"lemma": "ржд", "pos": "NOUN",
                             "entry_type": "abbreviation"}],
                "reason": "Railways abbreviation",
            }]}
            result = apply_decisions(db, batch, proposal, "fixture")
            self.assertEqual(result["admitted"], 1)
            kind = db.execute(
                "SELECT entry_type FROM lexemes WHERE lemma='ржд'"
            ).fetchone()[0]
            self.assertEqual(kind, "abbreviation")
            self.assertEqual(db.execute(
                "SELECT entry_type FROM lexemes WHERE id=1"
            ).fetchone()[0], "word")

    def test_dotted_abbreviations_are_one_token_not_letters(self):
        tokens = tokenize("Это т. д. и т. е. Например, рис. 2.")
        surfaces = [surface for surface, _ in tokens]
        self.assertIn("т. д.", surfaces)
        self.assertIn("т. е.", surfaces)
        self.assertIn("рис.", surfaces)
        self.assertNotIn("д", surfaces)
        self.assertNotIn("е", surfaces)
        options = parse_forms("т. д.", FakeMorph())
        self.assertEqual(options[0]["entry_type"], "abbreviation")

    def test_rehearsal_never_writes_original(self):
        initial = self.live.read_bytes()
        report = rehearse(self.live, self.root / "work")
        self.assertTrue(report["success"])
        self.assertTrue(report["idempotent_schema"])
        self.assertEqual(report["classification"]["reclassified"], 2)
        self.assertEqual(initial, self.live.read_bytes())


if __name__ == "__main__":
    unittest.main()
