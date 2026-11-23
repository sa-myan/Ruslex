"""Pure validation regressions; runs without Django or a writable database."""

from types import SimpleNamespace
import unittest

from dictionary.validation import (
    BadRequest,
    external_url,
    fields,
    identifier,
    identity,
    string,
)


class ValidationTests(unittest.TestCase):
    def test_unknown_fields_are_rejected(self):
        self.assertEqual(fields({"meaning": "word"}, {"meaning"}), {"meaning": "word"})
        for invalid in ({"meaning": "word", "surprise": 1}, ["meaning"], None):
            with self.subTest(invalid=invalid), self.assertRaises(BadRequest):
                fields(invalid, {"meaning"})

    def test_optional_empty_strings_are_allowed_but_nulls_rejected_when_required(self):
        self.assertEqual(string({"notes": "   "}, "notes", required=False), "")
        self.assertIsNone(string({}, "notes", required=False))
        with self.assertRaises(BadRequest):
            string({"meaning": None}, "meaning")
        with self.assertRaises(BadRequest):
            string({"notes": "x" * 5}, "notes", maxlen=4)

    def test_ids_are_positive_integers_and_not_booleans(self):
        self.assertEqual(identifier({"id": 3}, "id"), 3)
        self.assertIsNone(identifier({"id": ""}, "id", nullable=True))
        for value in (True, False, 0, -2, "3", 3.0, [], {}):
            with self.subTest(value=value), self.assertRaises(BadRequest):
                identifier({"id": value}, "id")

    def test_russian_lemma_normalization(self):
        result = identity({"lemma": "  СЁСТРА́  ", "pos": "NOUN"})
        self.assertEqual(result["lemma"], "сёстра")
        self.assertEqual(result["entry_type"], "word")
        self.assertEqual(result["aspect"], None)

    def test_expressions_and_partial_identity_updates(self):
        expression = identity({"lemma": "  делать  вид ", "pos": "VERB", "entry_type": "expression"})
        self.assertEqual(expression["lemma"], "делать вид")
        current = SimpleNamespace(
            lemma="делать", pos="VERB", entry_type="word",
            aspect="imperfective", animacy=None,
        )
        self.assertEqual(identity({"lemma": "сделать"}, current)["aspect"], "imperfective")
        self.assertEqual(identity({"pos": "NOUN"}, current)["aspect"], None)

    def test_invalid_lexeme_values_never_raise_type_errors(self):
        invalid_payloads = [
            {"lemma": "тест", "pos": "NOUN", "entry_type": []},
            {"lemma": "тест", "pos": "VERB", "aspect": []},
            {"lemma": "тест", "pos": "NOUN", "animacy": {}},
            {"lemma": "test", "pos": "NOUN"},
            {"lemma": "тест", "pos": "UNKNOWN"},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(BadRequest):
                identity(payload)

    def test_absolute_links_accept_http_without_credentials(self):
        self.assertEqual(external_url({"url": "https://example.org/path?q=1"}),
                         "https://example.org/path?q=1")
        for url in (
            "javascript:alert(1)", "//example.org", "https://user@example.org",
            "https://example.org:99999", "https://example.org/a b",
            "ftp://example.org", "https://", 44,
        ):
            with self.subTest(url=url), self.assertRaises(BadRequest):
                external_url({"url": url})


if __name__ == "__main__":
    unittest.main()
