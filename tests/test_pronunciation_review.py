"""Pronunciation review migration never changes existing dictionary decisions."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from processing.pronunciation_review import initialize, plan, candidates_plan, refresh_candidates
from processing.pronunciations import initialize as init_stress

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class PronunciationReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.live = self.root / "lexicon.db"
        self.backups = self.root / "backups"
        with sqlite3.connect(self.live) as db:
            db.executescript(SCHEMA.read_text())
            db.executemany(
                """INSERT INTO lexemes(lemma,pos,entry_type,human_status)
                   VALUES (?,?,?,?)""",
                [
                    ("писать", "VERB", "word", "kept"),
                    ("вуз", "NOUN", "word", "kept"),
                    ("тест", "NOUN", "word", "hidden"),
                ],
            )
        init_stress(self.live, self.backups)

    def test_read_only_preview_and_safe_idempotent_install(self):
        before = self.live.read_bytes()
        preview = plan(self.live)
        self.assertEqual(preview["unresolved"], 2)
        self.assertEqual(preview["pending"], 2)
        self.assertFalse(preview["schema_ready"])
        self.assertEqual(before, self.live.read_bytes())
        applied = initialize(self.live, self.backups)
        self.assertTrue(applied["changed"])
        self.assertFalse(initialize(self.live, self.backups)["changed"])
        with sqlite3.connect(self.live) as db:
            db.execute(
                """INSERT INTO pronunciation_review_queue(lexeme_id,note)
                   VALUES (1,'needs meaning-specific reading')""",
            )
            db.commit()
        updated = plan(self.live)
        self.assertEqual(updated["pending"], 1)
        self.assertEqual(updated["deferred"], 1)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertTrue(list(self.backups.glob("before-stress-pronunciation-review-queue-*.db")))

    def test_existing_pronunciations_are_excluded(self):
        initialize(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            db.execute(
                """INSERT INTO lexeme_pronunciations(
                       lexeme_id,stressed,source,reference_id,reference_fingerprint,
                       verification,is_primary,created_at
                   ) VALUES(1,'писа́ть','manual','','','verified',1,datetime('now'))"""
            )
            db.commit()
        self.assertEqual(plan(self.live)["pending"], 1)


    def test_source_backed_and_disputed_readings_stay_pending(self):
        initialize(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            db.execute(
                """INSERT INTO lexeme_pronunciations(
                     lexeme_id,stressed,source,reference_id,reference_fingerprint,
                     verification,is_primary,created_at)
                   VALUES(1,'писа́ть','openrussian','a','','source_backed',1,datetime('now'))"""
            )
            db.execute(
                """INSERT INTO pronunciation_review_queue(lexeme_id,note)
                   VALUES(1,'check source meaning')"""
            )
        self.assertEqual(plan(self.live)["deferred"], 1)
        with sqlite3.connect(self.live) as db:
            db.execute(
                "UPDATE lexeme_pronunciations SET verification='disputed' WHERE lexeme_id=1"
            )
        self.assertEqual(plan(self.live)["deferred"], 1)
        with sqlite3.connect(self.live) as db:
            db.execute(
                "UPDATE lexeme_pronunciations SET verification='verified' WHERE lexeme_id=1"
            )
        self.assertEqual(plan(self.live)["unresolved"], 1)
        self.assertEqual(plan(self.live)["deferred"], 0)

    def test_upgrade_existing_queue_schema_keeps_deferrals(self):
        with sqlite3.connect(self.live) as db:
            db.executescript("""
                CREATE TABLE pronunciation_review_queue(
                    lexeme_id INTEGER PRIMARY KEY REFERENCES lexemes(id),
                    note TEXT NOT NULL DEFAULT '',
                    deferred_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO pronunciation_review_queue(lexeme_id,note)
                VALUES(1,'keep me');
            """)
        self.assertFalse(plan(self.live)["schema_ready"])
        initialize(self.live, self.backups)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute(
                "SELECT note FROM pronunciation_review_queue WHERE lexeme_id=1"
            ).fetchone()[0], "keep me")
            self.assertTrue(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='pronunciation_review_candidates'"
            ).fetchone())

    def test_offline_candidate_cache_preserves_homographs_without_automatic_saves(self):
        reference = self.root / "openrussian.db"
        with sqlite3.connect(reference) as db:
            db.executescript("""
                CREATE TABLE words(
                    id TEXT, bare TEXT, accented TEXT, type TEXT, rank TEXT, level TEXT
                );
                CREATE TABLE translations(
                    id TEXT, lang TEXT, word_id TEXT, tl TEXT
                );
            """)
            db.executemany("INSERT INTO words VALUES(?,?,?,?,?,?)", [
                ("a", "писать", "пи'сать", "verb", "", ""),
                ("b", "писать", "писа'ть", "verb", "", ""),
                ("c", "вуз", "вуз", "noun", "", ""),
            ])
            db.executemany("INSERT INTO translations VALUES(?,?,?,?)", [
                ("1", "en", "a", "to urinate"),
                ("2", "en", "b", "to write"),
            ])
        initialize(self.live, self.backups)
        before = self.live.read_bytes()
        proposal = candidates_plan(self.live, reference)
        self.assertEqual(proposal["candidate_rows"], 3)
        self.assertEqual(proposal["entries_with_options"], 2)
        self.assertEqual(before, self.live.read_bytes())
        refreshed = refresh_candidates(self.live, reference, self.backups)
        self.assertEqual(refreshed["cached_options"], 3)
        with sqlite3.connect(self.live) as db:
            rows = db.execute(
                """SELECT reading,reference_glosses FROM pronunciation_review_candidates
                   WHERE lexeme_id=1 ORDER BY reading"""
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r[0] for r in rows}, {"пи́сать", "писа́ть"})
            self.assertNotEqual(rows[0][1], rows[1][1])
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM lexeme_pronunciations"
            ).fetchone()[0], 0)
        refresh_candidates(self.live, reference, self.backups)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM pronunciation_review_candidates"
            ).fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
