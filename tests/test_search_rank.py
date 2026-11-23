"""Pure-Python relevance regression against v3's verified SQLite output."""
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
import unittest
from pathlib import Path
from dictionary.search_rank import folded,english_quality,score

ROOT=Path(__file__).resolve().parents[1]

class SearchParityTests(unittest.TestCase):
    def test_english_word_boundary(self):
        self.assertEqual(english_quality('to read', 'read'),2)
        self.assertEqual(english_quality('reading', 'read'),1)
        for text in ('already', 'bread', 'spread'):
            self.assertEqual(english_quality(text,'read'),0)

    @unittest.skipUnless((ROOT / "data/lexicon.db").is_file(), "Optional historical fixture not available")
    def test_v3_reference_order(self):
        data=json.loads((ROOT/'tests/v3_search_fixtures.json').read_text())
        db=sqlite3.connect(ROOT/'data/lexicon.db')
        db.row_factory=sqlite3.Row
        words=[dict(row) for row in db.execute("SELECT id,lemma,human_status FROM lexemes ORDER BY id")]
        senses={}
        for row in db.execute('SELECT lexeme_id,meaning,description FROM senses WHERE active=1 ORDER BY id'):
            senses.setdefault(row['lexeme_id'],[]).append(SimpleNamespace(meaning=row['meaning'],description=row['description']))
        for query,expected in data.items():
            q=folded(query)
            eng=bool(__import__('re').search('[a-z]',q)) and not bool(__import__('re').search('[а-я]',q))
            matches=[]
            for w in words:
                if w['human_status']=='hidden':continue
                tier=score(w['lemma'],senses.get(w['id'],[]),q,english=eng) if q else 0
                if tier is not None:
                    matches.append((tier,len(w['lemma']),folded(w['lemma']),w['id']))
            if q: matches.sort()
            else:matches.sort(key=lambda r:r[3])
            ids=[r[3] for r in matches[:15]]
            with self.subTest(query=query):
                self.assertEqual((len(matches),ids),(expected['total'],expected['ids']))
        db.close()
