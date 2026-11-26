"""Pronunciation review migration never changes existing dictionary decisions."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from processing.pronunciation_review import initialize, plan
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


if __name__ == "__main__":
    unittest.main()
