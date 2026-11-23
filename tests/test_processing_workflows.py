"""Safety tests for the new VPS-only OCR and append-only promotion workflow."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace

from processing.forms import apply_decisions, review_batch
from processing.ocr import import_book, input_pages, inspect, tokenize
from processing.promotion import create_workspace, plan, promote
from processing.storage import write_database

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class FakeMorph:
    def parse(self, form):
        lemma = {"книги": "книга", "дом": "дом", "мама": "мама"}.get(form, form)
        return [SimpleNamespace(normal_form=lemma, tag=SimpleNamespace(POS="NOUN"),
                                is_known=True)]


class ProcessingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / "live.db"
        db = sqlite3.connect(self.live)
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO lexemes(lemma,pos,human_status,notes) VALUES('дом','NOUN','kept','manual note')")
        db.execute("INSERT INTO senses(lexeme_id,meaning) VALUES(1,'house')")
        db.commit()
        db.close()
        self.workspace = self.root / "new_book"
        create_workspace(self.live, self.workspace)
        self.ocr = self.root / "page-1.md"
        self.ocr.write_text("Мама читает книги. Дом большой. Мама любит книги.", encoding="utf-8")

    def import_page(self):
        with write_database(self.workspace / "candidate.db") as db:
            return import_book(db, title="Book Two", edition="2026", source=self.ocr,
                               first=1, last=1, analyzer=FakeMorph())

    def test_ocr_and_append_only_promotion_preserve_manual_editing(self):
        result = self.import_page()
        self.assertEqual(result["pages_added"], 1)
        self.assertGreater(result["new_forms_for_AI"], 0)
        with write_database(self.workspace / "candidate.db") as db:
            sample = review_batch(db, "Book Two", 20)
            decisions = {"results": [
                {"id": entry["id"], "decision": "admit", "confidence": "high",
                 "entries": [{"lemma": entry["analyses"][0]["lemma"],
                              "pos": entry["analyses"][0]["pos"]}],
                 "reason": "valid form"} for entry in sample
            ]}
            result = apply_decisions(db, sample, decisions, "mock")
            self.assertEqual(result.get("admitted"), len(sample))
        preview = plan(self.live, self.workspace)
        self.assertTrue(preview["append_only"])
        self.assertGreater(preview["total_new_rows"], 0)
        outcome = promote(self.live, self.workspace, self.root / "backups", confirmed=True)
        self.assertTrue(outcome["promoted"])
        self.assertTrue(Path(outcome["pre_promotion_backup"]).exists())
        with closing(sqlite3.connect(self.live)) as db:
            self.assertEqual(db.execute("SELECT notes FROM lexemes WHERE id=1").fetchone()[0],
                             "manual note")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM senses WHERE lexeme_id=1").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM books").fetchone()[0], 1)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM lexeme_pages").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_import_same_page_is_idempotent_and_changed_ocr_is_rejected(self):
        self.assertEqual(self.import_page()["pages_added"], 1)
        self.assertEqual(self.import_page()["pages_skipped"], 1)
        self.ocr.write_text("Different text.", encoding="utf-8")
        with write_database(self.workspace / "candidate.db") as db:
            with self.assertRaisesRegex(ValueError, "different OCR"):
                import_book(db, title="Book Two", edition="2026", source=self.ocr,
                            first=1, last=1, analyzer=FakeMorph())

    def test_modified_candidate_existing_entry_is_blocked(self):
        with write_database(self.workspace / "candidate.db") as db:
            db.execute("UPDATE lexemes SET notes='AI overwrote notes' WHERE id=1")
        with self.assertRaisesRegex(ValueError, "modified existing lexemes"):
            plan(self.live, self.workspace)

    def test_concurrent_live_edit_blocks_promotion(self):
        self.import_page()
        with closing(sqlite3.connect(self.live)) as db, db:
            db.execute("UPDATE lexemes SET notes='New human note' WHERE id=1")
        with self.assertRaisesRegex(RuntimeError, "Live dictionary changed"):
            plan(self.live, self.workspace)
        with self.assertRaises(RuntimeError):
            promote(self.live, self.workspace, self.root / "backups", confirmed=True)
        with closing(sqlite3.connect(self.live)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM books").fetchone()[0], 0)

    def test_incomplete_ai_batch_does_not_write(self):
        self.import_page()
        with write_database(self.workspace / "candidate.db") as db:
            batch = review_batch(db, "Book Two", 20)
            with self.assertRaisesRegex(ValueError, "one decision"):
                apply_decisions(db, batch, {"results": []}, "mock")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reviews WHERE status='pending'").fetchone()[0],
                             len(batch))

    def test_mistral_page_directory_and_zip(self):
        folder = self.root / "ocr-pages"
        first = folder / "000000-000002" / "pages" / "page-0"
        second = folder / "000000-000002" / "pages" / "page-1"
        for path, index in ((first, 0), (second, 1)):
            path.mkdir(parents=True)
            (path / "markdown.md").write_text(f"Русский текст {index}", encoding="utf-8")
            (path / "metadata.json").write_text(json.dumps({"page_index": index}), encoding="utf-8")
        self.assertEqual([n for n, _ in input_pages(folder)], [1, 2])
        archive = self.root / "ocr-pages.zip"
        with zipfile.ZipFile(archive, "w") as output:
            for file in folder.rglob("*"):
                if file.is_file():
                    output.write(file, file.relative_to(folder))
        self.assertEqual([n for n, _ in input_pages(archive)], [1, 2])

    def test_ambiguous_book_title_does_not_mix_editions(self):
        from processing.storage import inputs
        with write_database(self.workspace / "candidate.db") as db:
            db.execute("INSERT INTO books(title,edition) VALUES('Repeated Title','2024')")
            db.execute("INSERT INTO books(title,edition) VALUES('Repeated Title','2026')")
            with self.assertRaisesRegex(ValueError, "multiple editions"):
                review_batch(db, "Repeated Title", 10)
            with self.assertRaisesRegex(ValueError, "multiple editions"):
                list(inputs(db, "lexemes", book="Repeated Title"))

    def test_markdown_page_markers_and_tokenization(self):
        text = "<!-- page: 5 -->\nКниги, книги.\n<!-- page: 6 -->\nМама."
        marker_file = self.root / "pages.md"
        marker_file.write_text(text, encoding="utf-8")
        self.assertEqual([n for n, _ in input_pages(marker_file)], [5, 6])
        self.assertEqual(inspect(marker_file)["pages"], 2)
        self.assertEqual([form for form, _ in tokenize("Книги, книги.")], ["книги", "книги"])


if __name__ == "__main__":
    unittest.main()
