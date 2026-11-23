"""Read-only sanity checks for the exact supplied v3 SQLite snapshot."""

from pathlib import Path
import sqlite3
import unittest

DATABASE = Path(__file__).resolve().parents[1] / "data" / "lexicon.db"


class SuppliedSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.database.close()

    def test_integrity(self):
        result = self.database.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(result, "ok")
        self.assertEqual(self.database.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reference_counts(self):
        expected = {"lexemes": 1710, "senses": 2954, "lexeme_relations": 361}
        for table, count in expected.items():
            with self.subTest(table=table):
                actual = self.database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                self.assertEqual(actual, count)

    def test_sense_specific_links_remain_present(self):
        count = self.database.execute("""
            SELECT COUNT(*) FROM lexeme_relations
            WHERE source_sense_id IS NOT NULL OR target_sense_id IS NOT NULL
        """).fetchone()[0]
        self.assertGreater(count, 0)

    def test_no_django_tables_in_dictionary(self):
        table = self.database.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('auth_user', 'django_session', 'django_migrations')
        """).fetchone()
        self.assertIsNone(table)


if __name__ == "__main__":
    unittest.main()
