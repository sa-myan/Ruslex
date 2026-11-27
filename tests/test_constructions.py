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
    validate, pages_preview, curate,
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

    def test_page_preview_and_targeted_scan_are_read_only_and_scoped(self):
        with self.assertRaisesRegex(ValueError, "both --first-page"):
            with sqlite3.connect(self.live) as db:
                db.row_factory = sqlite3.Row
                sources(db, book="First Book", kind="pages", first_page=2)
        with self.assertRaisesRegex(ValueError, "requires --kind pages"):
            with sqlite3.connect(self.live) as db:
                db.row_factory = sqlite3.Row
                sources(db, book="First Book", kind="all", first_page=2, last_page=2)
        before = self.live.read_bytes()
        view = pages_preview(self.live, book="First Book", contains="больше")
        self.assertEqual(view["data_mutation"], "none")
        self.assertEqual(view["pages"][0]["pdf_page"], 2)
        self.assertEqual(view["matching_pages"], 1)
        self.assertEqual(pages_preview(self.live, book="First Book",
                                       contains="not in OCR")["matching_pages"], 0)
        self.assertEqual(self.live.read_bytes(), before)
        with patch("processing.constructions.opencode", side_effect=self.fake):
            report = scan(self.live, self.work, book="First Book", model="fake",
                          kind="pages", first_page=2, last_page=2, max_batches=1)
        self.assertEqual(report["page_range"], [2, 2])
        self.assertEqual(report["remaining_batches"], 0)
        self.assertEqual(proposals(self.work)["page_range"], [2, 2])
        with self.assertRaisesRegex(ValueError, "page range changed"):
            scan(self.live, self.work, book="First Book", model="fake",
                 kind="pages", first_page=1, last_page=1, dry_run=True)
        self.assertEqual(self.live.read_bytes(), before)

    def test_invalid_model_proposal_is_repaired_and_rejected_output_saved(self):
        malformed = {"results": [{
            "id": "e:1", "classification": "expression_only", "candidates": [],
        }, {
            "id": "p:10:0", "classification": "page", "candidates": [{
                "pattern": "X and Y", "meaning": "A grammar construction",
                "grammar": "some rule",
                "evidence": "Чем больше читаешь, тем больше узнаёшь.",
                "example_russian": "Чем больше читаешь, тем больше узнаёшь.",
                "example_english": "The more you read, the more you learn.",
            }],
        }]}
        corrected = {"results": [{
            "id": "e:1", "classification": "expression_only", "candidates": [],
        }, {
            "id": "p:10:0", "classification": "page", "candidates": [{
                "pattern": "чем X, тем Y", "meaning": "proportional comparison",
                "grammar": "comparative correlative",
                "evidence": "Чем больше читаешь, тем больше узнаёшь.",
                "example_russian": "Чем больше читаешь, тем больше узнаёшь.",
                "example_english": "The more you read, the more you learn.",
            }],
        }]}
        before = self.live.read_bytes()
        with patch("processing.constructions.opencode", side_effect=[malformed, corrected]) as model:
            result = scan(self.live, self.work, book="First Book",
                          model="fake", max_batches=1)
        self.assertEqual(model.call_count, 2)
        self.assertIn("VALIDATION REPAIR", model.call_args.args[0])
        self.assertEqual(result["completed_batches"], 1)
        self.assertEqual(self.live.read_bytes(), before)
        rejected = self.work / "rejected" / "000001-attempt1.json"
        self.assertTrue(rejected.is_file())
        self.assertIn("Russian canonical pattern",
                      json.loads(rejected.read_text(encoding="utf-8"))["validation_error"])
        self.assertEqual(
            json.loads((self.work / "batches" / "000001.json").read_text(encoding="utf-8")),
            corrected,
        )
        self.assertEqual([x["pattern"] for x in proposals(self.work)["proposals"]],
                         ["чем X, тем Y"])

    def test_repair_exhaustion_preserves_earlier_batches_for_resumption(self):
        with sqlite3.connect(self.live) as db:
            for page_id, markdown in (
                (11, "Чем больше работаешь, тем быстрее учишься."),
                (12, "Чем больше спишь, тем лучше."),
                (13, "Чем раньше уйдёшь, тем раньше придёшь."),
            ):
                db.execute(
                    """INSERT INTO pages(id,book_id,pdf_page,printed_page,markdown,source)
                       VALUES(?,1,?,?,?, 'test')""",
                    (page_id, page_id, page_id, markdown),
                )
            db.commit()

        invalid = {"results": []}

        def valid_pages(prompt, *args):
            payload = json.loads(prompt.split("SOURCE INPUT (JSON): ", 1)[1])
            return {"results": [
                {"id": row["id"], "classification": "page", "candidates": []}
                for row in payload
            ]}

        def fail_second_batch(prompt, *args):
            if "VALIDATION REPAIR" in prompt or '"p:12:0"' in prompt:
                return invalid
            return valid_pages(prompt, *args)

        with patch("processing.constructions.opencode", side_effect=fail_second_batch) as model:
            with self.assertRaisesRegex(ValueError, "failed validation after 3 responses"):
                scan(self.live, self.work, book="First Book", kind="pages",
                     model="fake", max_batches=2)
        self.assertEqual(model.call_count, 4)
        first_file = self.work / "batches" / "000001.json"
        self.assertTrue(first_file.is_file())
        self.assertFalse((self.work / "batches" / "000002.json").exists())
        for attempt in (1, 2, 3):
            self.assertTrue((self.work / "rejected" /
                             f"000002-attempt{attempt}.json").is_file())
        saved_bytes = first_file.read_bytes()

        # Only the failed batch is resubmitted to the model.
        with patch("processing.constructions.opencode", side_effect=valid_pages) as resumed:
            result = scan(self.live, self.work, book="First Book", kind="pages",
                          model="fake", max_batches=1)
        self.assertEqual(result["remaining_batches"], 0)
        self.assertEqual(resumed.call_count, 1)
        self.assertEqual(first_file.read_bytes(), saved_bytes)

    def test_strict_quality_gate_discards_basic_grammar_and_deduplicates_period(self):
        ordinary = ["Это X", "Это X.", "X ли Y", "X? (ИК-3)", "а X?"]
        good = ["чем X, тем Y", "не столько X, сколько Y",
                "стоит только X, как Y", "дело не в X, а в Y",
                "не успел X, как Y"]
        input_response = {"results": [{
            "id": "p:10:0", "classification": "page",
            "candidates": [{"pattern": p} for p in ordinary + good],
        }]}
        original = json.dumps(input_response, ensure_ascii=False)
        cleaned = curate(input_response)
        self.assertEqual(
            [r["pattern"] for r in cleaned["results"][0]["candidates"]], good)
        self.assertEqual(
            [r["pattern"] for r in cleaned["excluded_candidates"]], ordinary)
        self.assertEqual(json.dumps(input_response, ensure_ascii=False), original)
        self.assertEqual(key("Это X"), key("Это X."))

    def test_trivial_ai_proposals_are_excluded_from_saved_batch_plan(self):
        basic = {
            "id": "p:10:0", "classification": "page", "candidates": [{
                "pattern": "Это X", "meaning": "Basic identification",
                "grammar": "Nominative noun after это",
                "evidence": "Чем больше читаешь, тем больше узнаёшь.",
                "example_russian": "Это моя книга.",
                "example_english": "This is my book.",
            }],
        }
        with patch("processing.constructions.opencode",
                   return_value={"results": [
                       {"id": "e:1", "classification": "expression_only", "candidates": []},
                       basic,
                   ]}) as model:
            scan(self.live, self.work, book="First Book", model="fake")
            self.assertEqual(model.call_count, 1)
        plan = proposals(self.work)
        self.assertEqual(plan["proposals"], [])
        self.assertEqual(plan["excluded_candidates"][0]["pattern"], "Это X")
        self.assertEqual(plan["remaining_batches"], 0)

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
