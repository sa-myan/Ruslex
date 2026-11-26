"""Offline stress enrichment regression checks; never touches production."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from processing.form_stress import initialize, plan, apply, rehearse
from processing.paradigms import initialize as initialize_forms, fold

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class FormStressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live = self.root / "lexicon.db"
        self.ref = self.root / "openrussian.db"
        self.backups = self.root / "backups"
        with sqlite3.connect(self.live) as db:
            db.executescript(SCHEMA.read_text())
            db.executemany(
                "INSERT INTO lexemes(lemma,pos,human_status) VALUES (?,?,?)",
                [("читать", "VERB", "kept"),
                 ("замок", "NOUN", "kept"),
                 ("небо", "NOUN", "kept"),
                 ("видеть", "VERB", "hidden")],
            )
        initialize_forms(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            rows = [
                (1, "читать", "VERB", "читаю", "читаю", "VERB,1per,pres,sing"),
                (1, "читать", "VERB", "читая", "читая", "GRND,pres"),
                (1, "читать", "VERB", "читающий", "читающий", "PRTF,pres,actv,masc,sing,nomn"),
                (2, "замок", "NOUN", "замка", "замка", "NOUN,gent,sing"),
                (3, "небо", "NOUN", "неба", "неба", "NOUN,gent,sing"),
                (4, "видеть", "VERB", "вижу", "вижу", "VERB,1per,pres,sing"),
            ]
            db.executemany(
                """INSERT INTO lexeme_forms
                   (lexeme_id,lemma_at_generation,pos_at_generation,form,form_key,grammemes,created_at)
                   VALUES(?,?,?,?,?,?,datetime('now'))""",
                [(a, b, pos, form, fold(form), tags)
                 for a, b, pos, form, _key, tags in rows],
            )
        with sqlite3.connect(self.ref) as db:
            db.executescript("""
                CREATE TABLE words(id TEXT,bare TEXT,accented TEXT,type TEXT,rank TEXT,level TEXT);
                CREATE TABLE words_forms(word_id TEXT,form TEXT,form_type TEXT);
            """)
            db.executemany("INSERT INTO words VALUES (?,?,?,?,?,?)", [
                ("5", "читать", "чита'ть", "verb", "", ""),
                ("10", "замок", "за'мок", "noun", "", ""),
                ("11", "замок", "замо'к", "noun", "", ""),
                ("12", "небо", "не'бо", "noun", "", ""),
                ("13", "видеть", "ви'деть", "verb", "", ""),
            ])
            db.executemany("INSERT INTO words_forms VALUES (?,?,?)", [
                ("5", "чита'ю", "present_1sg"),
                ("5", "чита'я", "gerund"),
                ("5", "чита'ющий", "participle"),
                ("10", "за'мка", "genitive"),
                ("11", "замка'", "genitive"),
                ("12", "неба", "genitive"),  # missing stress: do not invent
                ("13", "ви'жу", "present_1sg"),
            ])

    def test_stress_from_same_lemma_only_and_safe_abstention(self):
        before = self.live.read_bytes()
        p = plan(self.live, self.ref)
        self.assertFalse(p["schema_ready"])
        self.assertEqual(p["safe_candidates"], 3, p)
        self.assertEqual(before, self.live.read_bytes())
        initialize(self.live, self.backups)
        result = apply(self.live, self.ref, self.backups)
        self.assertEqual(result["inserted"], 3)
        self.assertEqual(apply(self.live, self.ref, self.backups)["inserted"], 0)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(
                set(db.execute("SELECT stressed FROM lexeme_form_stress").fetchall()),
                {("чита́ю",), ("чита́я",), ("чита́ющий",)},
            )
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_pinned_homograph_reference_can_be_used(self):
        # Before the stress migration is installed, ambiguity forbids a guess.
        self.assertEqual(plan(self.live, self.ref)["safe_candidates"], 3, plan(self.live, self.ref))
        with sqlite3.connect(self.live) as db:
            db.executescript("""
                CREATE TABLE lexeme_pronunciations(
                    id INTEGER PRIMARY KEY, lexeme_id INTEGER,
                    stressed TEXT,source TEXT,verification TEXT,reference_id TEXT);
            """)
            db.execute(
                "INSERT INTO lexeme_pronunciations(lexeme_id,stressed,source,verification,reference_id)"
                " VALUES(2,'за́мок','openrussian','source_backed','10')"
            )
        self.assertEqual(plan(self.live, self.ref)["safe_candidates"], 4)

    def test_rehearsal_does_not_touch_live(self):
        before = (self.live.read_bytes(), self.ref.read_bytes())
        report = rehearse(self.live, self.ref, self.root / "work")
        self.assertTrue(report["success"])
        self.assertFalse(report["production_modified"])
        self.assertEqual(report["inserted"], 3)
        self.assertEqual(before, (self.live.read_bytes(), self.ref.read_bytes()))


if __name__ == "__main__":
    unittest.main()
