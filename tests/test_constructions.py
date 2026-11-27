"""Productive constructions: evidence validation, resumability and safe promotion."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from processing.constructions import (
    apply, evidence_text, initialize, installed, key, proposals, scan, sources,
    validate,
)
from processing.storage import write_database

SCHEMA = Path(__file__).parent / "fixtures" / "empty_lexicon_schema.sql"


class ConstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / "lexicon.db"
        with sqlite3.connect(self.live) as db:
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO books(id,title,edition) VALUES(1,'First Book','2026')"
            )
            db.execute(
                """INSERT INTO pages(id,book_id,pdf_page,printed_page,markdown,source)
                   VALUES(10,1,2,2,?, 'test')""",
                ("Чем больше читаешь, тем больше узнаёшь. "
                 "Не только он читает, но и она.",)
            )
            db.execute(
                """INSERT INTO lexemes(id,lemma,pos,entry_type,human_status,notes)
                   VALUES(1,'не только но и','OTHER','expression','kept','unchanged')"""
            )
            db.execute(
                """INSERT INTO senses(lexeme_id,meaning)
                   VALUES(1,'not only ... but also')"""
            )
            db.execute(
                """INSERT INTO lexeme_pages(lexeme_id,page_id,surface,context,count)
                   VALUES(1,10,'Не только он читает, но и она.',
                          'Не только он читает, но и она.',1)"""
            )
            db.commit()
        self.work = self.root / "scan"

    def fake(self, prompt, model, executable, timeout):
        inputs = json.loads(prompt.split("SOURCE INPUT (JSON): ", 1)[1])
        entries = []
        for item in inputs:
            if item["kind"] == "expression":
                entries.append({
                    "id": item["id"], "classification": "both", "candidates": [{
                        "pattern": "не только X, но и Y",
                        "meaning": "not only X but also Y",
                        "grammar": "correlative coordination",
                        "evidence": "не только но и",
                        "example_russian": "Не только он читает, но и она.",
                        "example_english": "Not only he reads, but she does too.",
                    }],
                })
            else:
                entries.append({
                    "id": item["id"], "classification": "page", "candidates": [{
                        "pattern": "чем X, тем Y",
                        "meaning": "proportional comparison",
                        "grammar": "comparative correlative",
                        "evidence": "Чем больше читаешь, тем больше узнаёшь.",
                        "example_russian": "Чем больше читаешь, тем больше узнаёшь.",
                        "example_english": "The more you read, the more you learn.",
                    }],
                })
        return {"results": entries}

    def test_grounded_scan_resume_then_approve_without_touching_expressions(self):
        before = self.live.read_bytes()
        dry = scan(self.live, self.work, book="First Book", model="fake", dry_run=True)
        self.assertEqual(dry["data_mutation"], "none")
        self.assertFalse(self.work.exists())
        with patch("processing.constructions.opencode", side_effect=self.fake) as model:
            first = scan(self.live, self.work, book="First Book", model="fake",
                         max_batches=1)
            self.assertEqual(first["completed_batches"], 1)
            second = scan(self.live, self.work, book="First Book", model="fake",
                          max_batches=1)
            self.assertEqual(second["remaining_batches"], 0)
            third = scan(self.live, self.work, book="First Book", model="fake",
                         max_batches=1)
            self.assertEqual(third["new_batches"], 0)
            self.assertEqual(model.call_count, 1)
        self.assertEqual(self.live.read_bytes(), before)
        report = proposals(self.work)
        self.assertEqual(report["remaining_batches"], 0)
        self.assertEqual(len(report["proposals"]), 2)
        self.assertEqual(
            {item["pattern"] for item in report["proposals"]},
            {"не только X, но и Y", "чем X, тем Y"},
        )
        with self.assertRaises(ValueError):
            apply(self.live, self.work, self.root / "backups",
                  approved=[1], confirmed=False)
        initialized = initialize(self.live, self.root / "backups")
        self.assertTrue(initialized["changed"])
        self.assertFalse(initialize(self.live, self.root / "backups")["changed"])
        applied = apply(self.live, self.work, self.root / "backups",
                        approved=[1, 2], confirmed=True)
        self.assertEqual(applied["new_constructions"], 2)
        self.assertEqual(applied["existing_expression_rows_modified"], 0)
        again = apply(self.live, self.work, self.root / "backups",
                      approved=[1, 2], confirmed=True)
        self.assertEqual(again["new_constructions"], 0)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute("SELECT notes FROM lexemes WHERE id=1").fetchone()[0],
                             "unchanged")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM constructions").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM construction_attestations").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM construction_expression_links").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_reject_fabricated_evidence_and_changed_book_page(self):
        batch = [{"id": "p:10:0", "kind": "page",
                  "evidence_base": "Чем больше читаешь, тем больше узнаёшь."}]
        response = {"results": [{"id": "p:10:0", "classification": "page",
                                "candidates": [{"pattern": "чем X, тем Y",
                                  "meaning": "correlation", "grammar": "comparison",
                                  "evidence": "no such Russian text",
                                  "example_russian": "Чем больше, тем лучше.",
                                  "example_english": "The more, the better."}]}]}
        with self.assertRaisesRegex(ValueError, "not attested"):
            validate(response, batch)
        with patch("processing.constructions.opencode", side_effect=self.fake):
            scan(self.live, self.work, book="First Book", model="fake")
        initialize(self.live, self.root / "backups")
        with write_database(self.live) as db:
            db.execute("UPDATE pages SET markdown='Completely changed' WHERE id=10")
        with self.assertRaisesRegex(RuntimeError, "Page text changed"):
            apply(self.live, self.work, self.root / "backups",
                  approved=[1, 2], confirmed=True)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM constructions").fetchone()[0], 0)

    def test_model_scope_and_invalid_responses(self):
        with sqlite3.connect(self.live) as db:
            db.row_factory = sqlite3.Row
            self.assertEqual(len(sources(db, book="First Book")), 2)
            with self.assertRaisesRegex(ValueError, "one edition"):
                sources(db, book="Unknown Book")
        with patch("processing.constructions.opencode", return_value={"results": []}):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                scan(self.live, self.work, book="First Book", model="fake")
        self.assertEqual(key("  ЧЕМ  X,  ТЕМ Y  "), "чем x, тем y")

    def test_pages_only_scan_skips_existing_expressions(self):
        with sqlite3.connect(self.live) as db:
            db.row_factory = sqlite3.Row
            selected = sources(db, book="First Book", kind="pages")
            self.assertEqual(len(selected), 1)
            self.assertTrue(all(row["kind"] == "page" for row in selected))
            expressions = sources(db, book="First Book", kind="expressions")
            self.assertEqual(len(expressions), 1)
            self.assertEqual(expressions[0]["kind"], "expression")
        with patch("processing.constructions.opencode", side_effect=self.fake):
            progress = scan(self.live, self.work, book="First Book", model="fake",
                            kind="pages", max_batches=1)
        self.assertEqual(progress["source_kind"], "pages")
        self.assertEqual(progress["completed_batches"], 1)
        self.assertEqual(progress["remaining_batches"], 0)
        report = proposals(self.work)
        self.assertEqual(report["source_kind"], "pages")
        self.assertEqual(report["expression_review"], [])
        self.assertEqual([x["pattern"] for x in report["proposals"]],
                         ["чем X, тем Y"])
        with self.assertRaisesRegex(ValueError, "source kind changed"):
            scan(self.live, self.work, book="First Book", model="fake",
                 kind="expressions", dry_run=True)

    def test_old_rules_cannot_resume_or_approve(self):
        with patch("processing.constructions.opencode", side_effect=self.fake):
            scan(self.live, self.work, book="First Book", model="fake")
        manifest = self.work / "manifest.json"
        old = json.loads(manifest.read_text(encoding="utf-8"))
        old.pop("audit_rules_version")
        manifest.write_text(json.dumps(old), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "rules were updated"):
            scan(self.live, self.work, book="First Book", model="fake")
        initialize(self.live, self.root / "backups")
        with self.assertRaisesRegex(RuntimeError, "Old audit rules"):
            apply(self.live, self.work, self.root / "backups",
                  approved=[1], confirmed=True)
        with sqlite3.connect(self.live) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM constructions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
