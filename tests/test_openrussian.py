"""Offline OpenRussian reference regression tests with synthetic SQLite fixtures."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from processing import cli
from processing.openrussian import connect_reference, lookup, normalize_accented, match_capitalization, result
from processing.reference_audit import audit_entries, write_report
from processing.pronunciations import initialize, backfill_plan, apply_backfill


class OpenRussianTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reference = self.root / "openrussian.db"
        self.lexicon = self.root / "lexicon.db"
        with closing(sqlite3.connect(self.reference)) as db:
            db.executescript("""
                CREATE TABLE words(id TEXT, bare TEXT, accented TEXT, type TEXT, rank TEXT, level TEXT);
                CREATE TABLE translations(id TEXT, lang TEXT, word_id TEXT, tl TEXT);
                CREATE TABLE words_forms(id TEXT, word_id TEXT, form TEXT, form_type TEXT);
                CREATE TABLE verbs(word_id TEXT, aspect TEXT, partner TEXT);
            """)
            db.executemany("INSERT INTO words VALUES(?,?,?,?,?,?)", [
                ("1","замок","за'мок","noun","",""),
                ("2","замок","замо'к","noun","",""),
                ("3","елка","ёлка","noun","",""),
                ("4","читать","чита'ть","verb","",""),
                ("5","все","все","pronoun","",""),
                ("6","все","всё","pronoun","",""),
                ("7","молоко","молоко","noun","",""),
            ])
            db.execute("INSERT INTO translations VALUES(?,?,?,?)", ("a","en","4","to read"))
            db.execute("INSERT INTO translations VALUES(?,?,?,?)", ("b","de","4","lesen"))
            db.execute("INSERT INTO words_forms VALUES(?,?,?,?)", ("f","4","чита'ю","present_1sg"))
            db.execute("INSERT INTO verbs VALUES(?,?,?)", ("4","impf","прочита'ть,перечита'ть"))
            db.commit()
        with closing(sqlite3.connect(self.lexicon)) as db:
            db.executescript("""
                CREATE TABLE lexemes(id INTEGER PRIMARY KEY,lemma TEXT,pos TEXT,entry_type TEXT);
                INSERT INTO lexemes VALUES(1,'замок','NOUN','word');
                INSERT INTO lexemes VALUES(2,'елка','NOUN','word');
                INSERT INTO lexemes VALUES(3,'читать','VERB','word');
                INSERT INTO lexemes VALUES(4,'все','NPRO','word');
                INSERT INTO lexemes VALUES(5,'молоко','NOUN','word');
                INSERT INTO lexemes VALUES(6,'нетвсловаре','NOUN','word');
                INSERT INTO lexemes VALUES(7,'выражение','OTHER','expression');
            """)

    def test_stress_and_yo_are_preserved(self):
        self.assertEqual(normalize_accented("чита'ть"), ("чита\u0301ть", ()))
        self.assertEqual(normalize_accented("ёлка"), ("ёлка", ()))
        self.assertTrue(normalize_accented("молоко")[1])
        self.assertTrue(normalize_accented("мо'ло'ко")[1])

    def test_read_only_and_missing_database(self):
        with self.assertRaises(FileNotFoundError):
            with connect_reference(self.root / "missing.db"):
                pass
        self.assertFalse((self.root / "missing.db").exists())

    def test_multiple_headword_readings_remain_separate(self):
        with connect_reference(self.reference) as db:
            self.assertEqual({w.stressed for w in lookup(db, "замок")}, {"за\u0301мок", "замо\u0301к"})
            self.assertEqual({w.stressed for w in lookup(db, "все")}, {"все", "всё"})
            self.assertEqual(lookup(db, "елка")[0].stressed, "ёлка")

    def test_related_data_does_not_duplicate_word(self):
        with connect_reference(self.reference) as db:
            output = result(lookup(db, "читать")[0], db, include_forms=True)
        self.assertEqual(output["translations_en"], ["to read"])
        self.assertEqual(output["forms"][0]["stressed"], "чита\u0301ю")
        self.assertEqual(output["verbs"][0]["partner_spellings"], ["прочитать", "перечитать"])

    def test_audit_never_modifies_databases(self):
        original = (self.reference.read_bytes(), self.lexicon.read_bytes())
        with connect_reference(self.reference) as ref, closing(sqlite3.connect(self.lexicon)) as lex:
            lex.row_factory = sqlite3.Row
            rows = audit_entries(ref, lex)
        statuses = {r["lemma"]: r["status"] for r in rows}
        self.assertEqual(statuses["замок"], "ambiguous")
        self.assertEqual(statuses["елка"], "yo_review")
        self.assertEqual(statuses["читать"], "candidate")
        self.assertEqual(statuses["все"], "ambiguous")
        self.assertEqual(statuses["молоко"], "source_warning")
        self.assertEqual(statuses["нетвсловаре"], "not_found")
        self.assertEqual(len(rows), 6)
        summary = write_report(rows, self.root / "reports")
        self.assertEqual(summary["lexemes_checked"], 6)
        self.assertEqual(original, (self.reference.read_bytes(), self.lexicon.read_bytes()))

    def test_capitalization_is_preserved(self):
        self.assertEqual(match_capitalization("москва\u0301", "Москва"), "Москва\u0301")
        self.assertEqual(match_capitalization("ёлка", "Елка"), "Ёлка")
        self.assertEqual(match_capitalization("сло\u0301во", "СЛОВО"), "СЛО\u0301ВО")

    def test_hyphenated_headwords_and_pos_equivalences(self):
        self.assertEqual(normalize_accented("кто'-нибудь"), ("кто\u0301-нибудь", ()))
        from processing.openrussian import pos_code, candidate_words, ReferenceWord
        reading = ReferenceWord("x", "читать", "чита'ть", "читать",
                                "чита\u0301ть", "verb", "", "", ())
        self.assertEqual(candidate_words([reading], "INFN")[0], [reading])
        self.assertEqual(pos_code("adjective"), "ADJF")

    def test_yo_flag_is_independent(self):
        with connect_reference(self.reference) as ref, closing(sqlite3.connect(self.lexicon)) as lex:
            lex.row_factory = sqlite3.Row
            rows = {r["lemma"]: r for r in audit_entries(ref, lex)}
        self.assertEqual(rows["елка"]["status"], "yo_review")
        self.assertEqual(rows["елка"]["yo_check"], "different_spelling")
        self.assertFalse(rows["елка"]["safe_backfill"])
        self.assertEqual(rows["все"]["yo_check"], "different_spelling")
        self.assertFalse(rows["все"]["safe_backfill"])
        self.assertTrue(rows["читать"]["safe_backfill"])

    def test_orphan_apostrophe_is_source_warning_not_fatal(self):
        # Real OpenRussian dumps sometimes contain apostrophes which do not
        # follow vowels. They must not shift the capitalization index or
        # enter the automatic backfill.
        from processing.openrussian import normalize_accented
        normalized, warnings = normalize_accented("до'м'")
        self.assertTrue(warnings)
        self.assertEqual(match_capitalization(normalized, "Дом"), "До\u0301м'")
        with closing(sqlite3.connect(self.reference)) as ref:
            ref.execute(
                "INSERT INTO words VALUES(?,?,?,?,?,?)",
                ("orphan", "дом", "до'м'", "noun", "", ""),
            )
            ref.commit()
        with closing(sqlite3.connect(self.lexicon)) as lex:
            lex.execute(
                "INSERT INTO lexemes VALUES(8,'Дом','NOUN','word')"
            )
            lex.commit()
        with connect_reference(self.reference) as ref, closing(sqlite3.connect(self.lexicon)) as lex:
            lex.row_factory = sqlite3.Row
            rows = audit_entries(ref, lex)
        found = next(row for row in rows if row["lemma"] == "Дом")
        self.assertEqual(found["status"], "source_warning")
        self.assertFalse(found["safe_backfill"])

    def test_unalignable_reference_is_reported_not_fatal(self):
        with closing(sqlite3.connect(self.reference)) as ref:
            ref.execute(
                "INSERT INTO words VALUES(?,?,?,?,?,?)",
                ("misaligned", "читать", "чита'т\u0301ь", "verb", "", ""),
            )
            ref.commit()
        with connect_reference(self.reference) as ref, closing(sqlite3.connect(self.lexicon)) as lex:
            lex.row_factory = sqlite3.Row
            rows = audit_entries(ref, lex)
        item = next(row for row in rows if row["lemma"] == "читать")
        self.assertEqual(item["status"], "source_warning")
        self.assertFalse(item["safe_backfill"])

    def test_schema_and_backfill_preserve_original_headwords(self):
        backup_dir = self.root / "backups"
        before = self.lexicon.read_bytes()
        before_plan = backfill_plan(self.lexicon, self.reference)
        self.assertFalse(before_plan["schema_installed"])
        self.assertEqual(self.lexicon.read_bytes(), before)
        result = initialize(self.lexicon, backup_dir)
        self.assertTrue(result["changed"])
        self.assertFalse(initialize(self.lexicon, backup_dir)["changed"])
        self.assertGreaterEqual(backfill_plan(self.lexicon, self.reference)["safe_new_pronunciations"], 1)
        outcome = apply_backfill(self.lexicon, self.reference, backup_dir)
        self.assertEqual(outcome["inserted"], 1)
        self.assertEqual(apply_backfill(self.lexicon, self.reference, backup_dir)["inserted"], 0)
        with closing(sqlite3.connect(self.lexicon)) as db:
            self.assertEqual(db.execute(
                "SELECT stressed FROM lexeme_pronunciations"
            ).fetchall(), [("чита\u0301ть",)])
            self.assertEqual(db.execute(
                "SELECT lemma FROM lexemes WHERE id=3"
            ).fetchone()[0], "читать")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertTrue(list(backup_dir.glob("before-stress-*.db")))

    def test_cli_lookup(self):
        with patch.object(cli, "REFERENCE_DB", self.reference):
            with redirect_stdout(StringIO()) as output:
                cli.main(["reference", "lookup", "читать", "--forms"])
        data = json.loads(output.getvalue())
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["matches"][0]["forms"][0]["form_type"], "present_1sg")


if __name__ == "__main__":
    unittest.main()
