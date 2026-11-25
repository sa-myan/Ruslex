"""Offline morphology persistence safety tests; does not require pymorphy3."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from processing.paradigms import (
    generate, initialize, plan, backfill, rehearse, for_new_lexemes, fold,
)

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class FakeMorph:
    def parse(self, lemma):
        if lemma in {"замок", "тема"}:
            return [
                self.one(lemma, [lemma, lemma + "а"]),
                self.one(lemma, [lemma, lemma + "у"]),
            ]
        if lemma == "дом":
            return [self.one(lemma, ["дом", "дома", "дому", "домом"])]
        if lemma == "мама":
            return [self.one(lemma, ["мама", "мамы", "маме", "маму"])]
        return []

    def one(self, lemma, forms):
        lexeme = [
            SimpleNamespace(word=word, tag=SimpleNamespace(
                POS="NOUN", grammemes=frozenset(["NOUN", "nomn" if i == 0 else "gent"])
            ))
            for i, word in enumerate(forms)
        ]
        return SimpleNamespace(normal_form=lemma,
                               tag=SimpleNamespace(POS="NOUN"), lexeme=lexeme)


class ParadigmTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.live = self.root / "lexicon.db"
        with sqlite3.connect(self.live) as db:
            db.executescript(SCHEMA.read_text())
            db.executemany(
                "INSERT INTO lexemes(lemma,pos,human_status) VALUES (?,?,?)",
                [
                    ("дом", "NOUN", "kept"),
                    ("мама", "NOUN", "kept"),
                    ("замок", "NOUN", "kept"),
                    ("неважно", "ADVB", "kept"),
                    ("тема", "NOUN", "hidden"),
                ],
            )
        self.morph = FakeMorph()
        self.backups = self.root / "backups"

    def test_generate_abstains_on_ambiguous_paradigms(self):
        forms, reason = generate("замок", "NOUN", self.morph)
        self.assertEqual(forms, [])
        self.assertEqual(reason, "multiple_paradigms")
        self.assertEqual(generate("неважно", "ADVB", self.morph)[1], "unsupported_pos")
        self.assertEqual(fold("Ёлки"), "елки")

    def test_form_backfill_and_idempotence(self):
        before = self.live.read_bytes()
        preview = plan(self.live, self.morph)
        self.assertFalse(preview["schema_installed"])
        self.assertEqual(preview["eligible_headwords"], 2)
        self.assertEqual(preview["expected_form_rows"], 8)
        self.assertEqual(before, self.live.read_bytes())
        initialize(self.live, self.backups)
        first = backfill(self.live, self.backups, self.morph)
        self.assertEqual(first["generated"]["forms_added"], 8)
        self.assertEqual(first["data_mutation"], "forms_inserted")
        self.assertEqual(backfill(self.live, self.backups, self.morph)["data_mutation"], "none")
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_forms"
            ).fetchone()[0], 8)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_forms WHERE lexeme_id=5"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_forms WHERE lexeme_id=3"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_new_word_autofill_restricted_to_new_ids(self):
        initialize(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            result = for_new_lexemes(db, {2, 5}, self.morph)
            db.commit()
            self.assertEqual(result["forms_added"], 4)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_forms WHERE lexeme_id=1"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_forms WHERE lexeme_id=5"
            ).fetchone()[0], 0)

    def test_rehearsal_uses_copy(self):
        before = self.live.read_bytes()
        result = rehearse(self.live, self.root / "work", self.morph)
        self.assertTrue(result["success"])
        self.assertEqual(result["forms_total"], 8)
        self.assertEqual(result["second"].get("forms_added", 0), 0)
        self.assertEqual(before, self.live.read_bytes())


if __name__ == "__main__":
    unittest.main()
