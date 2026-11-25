"""Offline, synthetic tests of AI pronunciation exception workflow.

No network calls; AI responses are patched and every database is disposable.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.pronunciations import initialize
from processing.stress_ai import analyze, plan, apply, automatic_reasons, validate, evidence


class StressAITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live = self.root / "lexicon.db"
        self.reference = self.root / "reference.db"
        self.work = self.root / "work"
        self.backups = self.root / "backups"
        self.work.mkdir()
        with sqlite3.connect(self.live) as db:
            db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE lexemes(
                    id INTEGER PRIMARY KEY, lemma TEXT, pos TEXT,
                    entry_type TEXT, human_status TEXT
                );
                CREATE TABLE senses(
                    id INTEGER PRIMARY KEY, lexeme_id INTEGER REFERENCES lexemes(id),
                    meaning TEXT, active INTEGER DEFAULT 1
                );
                INSERT INTO lexemes VALUES(1,'писать','VERB','word','kept');
                INSERT INTO senses VALUES(4,1,'to write',1);
                INSERT INTO lexemes VALUES(2,'пропуск','NOUN','word','hidden');
                INSERT INTO senses VALUES(5,2,'pass',1);
                INSERT INTO lexemes VALUES(3,'лекарство','NOUN','word','kept');
                INSERT INTO senses VALUES(6,3,'medicine',1);
            """)
        with sqlite3.connect(self.reference) as db:
            db.executescript("""
                CREATE TABLE words(id TEXT,bare TEXT,accented TEXT,type TEXT,rank TEXT,level TEXT);
                CREATE TABLE translations(id TEXT,lang TEXT,word_id TEXT,tl TEXT);
                INSERT INTO words VALUES('10','писать','писа''ть','verb','','');
                INSERT INTO words VALUES('20','писать','пи''сать','verb','','');
                INSERT INTO words VALUES('30','пропуск','про''пуск','noun','','');
                INSERT INTO words VALUES('40','лекарство','ле''карство','noun','','');
                INSERT INTO words VALUES('50','лекарство','лека''рство','noun','','');
                INSERT INTO translations VALUES('1','en','10','write');
                INSERT INTO translations VALUES('2','en','20','urinate');
                INSERT INTO translations VALUES('3','en','40','medicine');
                INSERT INTO translations VALUES('4','en','50','medicine');
            """)
            # SQLite concatenation above uses adjacent SQL string literals,
            # but spelling of source accents is set explicitly for clarity.
            db.execute("UPDATE words SET accented=? WHERE id='10'", ("писа'ть",))
            db.execute("UPDATE words SET accented=? WHERE id='20'", ("пи'сать",))
            db.execute("UPDATE words SET accented=? WHERE id='30'", ("про'пуск",))
            db.execute("UPDATE words SET accented=? WHERE id='40'", ("ле'карство",))
            db.execute("UPDATE words SET accented=? WHERE id='50'", ("лека'рство",))
        initialize(self.live, self.backups)

    def vote(self, word_id, reading, reference_id, senses, *, action="select", confidence="high"):
        return {"results": [{"id": word_id, "action": action,
                            "reading": reading, "reference_id": reference_id,
                            "sense_ids": senses, "confidence": confidence,
                            "reason": "Reference gloss supports existing sense"}]}

    def test_auto_apply_one_meaning_distinct_homograph(self):
        before_headwords = self.live.read_bytes()
        first = self.vote(1, "писа́ть", "10", [4])
        with patch("processing.stress_ai.opencode", side_effect=[first, first]) as model:
            output = analyze(self.live, self.reference, self.work, name="trial",
                             model="provider/model-a", verify_model="provider/model-b",
                             batch_size=1, max_batches=1)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(output["completed"], 1)
        self.assertEqual(output["auto_eligible"], 1)
        plan_result = plan(self.live, self.reference, self.work, "trial")
        self.assertEqual(plan_result["auto_eligible"], 1)
        result = apply(self.live, self.reference, self.work, self.backups, "trial")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["data_mutation"], "pronunciations_inserted")
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute(
                "SELECT stressed,reference_id FROM lexeme_pronunciations"
            ).fetchall(), [("писа́ть", "10")])
            self.assertEqual(db.execute(
                "SELECT sense_id FROM sense_pronunciations"
            ).fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lexemes").fetchone()[0], 3)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertNotEqual(before_headwords, self.live.read_bytes())
        self.assertTrue(list(self.backups.glob("before-stress-ai-headwords-*.db")))

    def test_invalid_model_json_is_retried_without_losing_work(self):
        good = self.vote(1, "писа́ть", "10", [4])
        malformed = {"results": [{"id": 1, "action": "select"}]}
        with patch("processing.stress_ai.opencode", side_effect=[malformed, good]) as model:
            outcome = analyze(self.live, self.reference, self.work, name="repair",
                              model="provider/model-a", batch_size=1, max_batches=1)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(outcome["completed"], 1)
        self.assertEqual(outcome["auto_eligible"], 0)
        rejected = list((self.work / "stress_ai" / "repair" / "rejected").glob("*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(apply(self.live, self.reference, self.work,
                               self.backups, "repair")["inserted"], 0)

    def test_missing_verifier_never_auto_applies(self):
        first = self.vote(1, "писа́ть", "10", [4])
        with patch("processing.stress_ai.opencode", return_value=first):
            result = analyze(self.live, self.reference, self.work, name="solo",
                             model="provider/model-a", max_batches=1, batch_size=1)
        self.assertEqual(result["auto_eligible"], 0)
        self.assertEqual(apply(self.live, self.reference, self.work,
                               self.backups, "solo")["inserted"], 0)

    def test_altered_or_invented_readings_are_rejected(self):
        cases, _ = evidence(self.live, self.reference, self.work)
        case = next(c for c in cases if c["lemma"] == "писать")
        with self.assertRaises(ValueError):
            validate(self.vote(1, "пи́сать", "10", [4]), [case])
        with self.assertRaises(ValueError):
            validate(self.vote(1, "писа́ть", "404", [4]), [case])
        with self.assertRaises(ValueError):
            validate(self.vote(1, "писа́ть", "10", [9999]), [case])

    def test_shared_meaning_variants_are_never_auto_applied(self):
        cases, _ = evidence(self.live, self.reference, self.work)
        case = next(c for c in cases if c["lemma"] == "лекарство")
        vote = {"action": "select", "confidence": "high",
                "reading": "ле́карство", "reference_id": "40", "sense_ids": [6]}
        self.assertIn("overlapping_meanings_or_pronunciation_variants",
                      automatic_reasons(case, vote, vote))

    def test_evidence_excludes_hidden_entries(self):
        cases, _ = evidence(self.live, self.reference, self.work)
        self.assertEqual({c["id"] for c in cases}, {1, 3})

    def test_stale_run_rejected_after_manual_edit(self):
        first = self.vote(1, "писа́ть", "10", [4])
        with patch("processing.stress_ai.opencode", side_effect=[first, first]):
            analyze(self.live, self.reference, self.work, name="stale",
                    model="provider/model-a", verify_model="provider/model-b",
                    batch_size=1, max_batches=1)
        with sqlite3.connect(self.live) as db:
            db.execute("UPDATE senses SET meaning='to paint' WHERE id=4")
        with self.assertRaises(RuntimeError):
            plan(self.live, self.reference, self.work, "stale")


if __name__ == "__main__":
    unittest.main()
