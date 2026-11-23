#!/usr/bin/env python3
"""Read-only audit of an enriched Russian Lexicon SQLite database.

Writes a Markdown overview and CSV review queues. Does not modify the database.
Python 3.10+, standard library only.
"""
import argparse
import csv
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def connect_read_only(path):
    if not path.is_file():
        raise SystemExit(f"Database not found: {path}")
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def rows(db, sql, *params):
    return [dict(row) for row in db.execute(sql, params)]


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def csv_write(path, records, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def ident(relationship):
    a, b = relationship['source_lexeme_id'], relationship['target_lexeme_id']
    t = relationship['relation_type']
    if t in {'aspect_pair', 'synonym', 'antonym', 'related'}:
        a, b = min(a, b), max(a, b)
    return (t, a, b)


def make_audit(db, out, sample_size, seed):
    out.mkdir(parents=True, exist_ok=True)
    tables = {r['name'] for r in rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'lexemes', 'senses', 'lexeme_relations', 'examples', 'patterns'}
    if not required <= tables:
        raise SystemExit('Not a compatible lexicon database. Missing: ' + ', '.join(sorted(required-tables)))

    lexemes = rows(db, """SELECT l.id, l.lemma, l.pos, l.entry_type, l.human_status,
        l.aspect, l.animacy, count(DISTINCT s.id) AS senses
        FROM lexemes l LEFT JOIN senses s ON s.lexeme_id=l.id AND s.active=1
        GROUP BY l.id ORDER BY l.id""")
    lex_by_id = {r['id']: r for r in lexemes}
    relation_records = rows(db, """SELECT id,source_lexeme_id,target_lexeme_id,
        relation_type,source_sense_id,target_sense_id,notes FROM lexeme_relations ORDER BY id""")
    link_groups = defaultdict(list)
    for rel in relation_records:
        link_groups[ident(rel)].append(rel)

    repeated_links = []
    duplicate_extras = 0
    for (typ, a, b), group in sorted(link_groups.items()):
        if len(group) < 2:
            continue
        duplicate_extras += len(group)-1
        la, lb = lex_by_id.get(a, {}), lex_by_id.get(b, {})
        repeated_links.append({
            'relation_type': typ, 'word_a_id': a, 'word_a': la.get('lemma','?'),
            'word_a_pos': la.get('pos','?'), 'word_b_id': b,
            'word_b': lb.get('lemma','?'), 'word_b_pos': lb.get('pos','?'),
            'rows': len(group), 'surplus_rows': len(group)-1,
            'relation_row_ids': ','.join(str(r['id']) for r in group),
            'source_sense_ids': ','.join(str(r['source_sense_id'] or '-') for r in group),
            'target_sense_ids': ','.join(str(r['target_sense_id'] or '-') for r in group),
            'interpretation': ('Likely redundant; aspect pairs normally connect lexemes'
                               if typ=='aspect_pair'
                               else 'Review: distinct sense-level links may be intentional'),
        })
    csv_write(out/'repeated_relationships.csv', repeated_links,
              ['relation_type','word_a_id','word_a','word_a_pos','word_b_id','word_b',
               'word_b_pos','rows','surplus_rows','relation_row_ids','source_sense_ids',
               'target_sense_ids','interpretation'])

    aspect_issues = []
    for rel in relation_records:
        if rel['relation_type'] != 'aspect_pair':
            continue
        a = lex_by_id.get(rel['source_lexeme_id'], {})
        b = lex_by_id.get(rel['target_lexeme_id'], {})
        if {a.get('aspect'), b.get('aspect')} != {'imperfective','perfective'}:
            aspect_issues.append({
                'relation_row_id': rel['id'], 'source': a.get('lemma','?'),
                'source_aspect': a.get('aspect'), 'target': b.get('lemma','?'),
                'target_aspect': b.get('aspect'),
                'issue': 'Aspect counterpart endpoints do not have opposite aspects',
            })
    csv_write(out/'aspect_pair_conflicts.csv', aspect_issues,
              ['relation_row_id','source','source_aspect','target','target_aspect','issue'])

    repeats = {}
    for kind, sql in {
        'sense': """SELECT lexeme_id AS word_id, lower(trim(meaning)) AS repeated_text,
                COUNT(*) AS copies, group_concat(id) AS row_ids
                FROM senses WHERE active=1 GROUP BY lexeme_id,lower(trim(meaning))
                HAVING count(*) > 1""",
        'pattern': """SELECT s.lexeme_id AS word_id, lower(trim(p.pattern)) AS repeated_text,
                COUNT(*) AS copies, group_concat(p.id) AS row_ids
                FROM patterns p JOIN senses s ON s.id=p.sense_id
                WHERE p.active=1 AND s.active=1
                GROUP BY p.sense_id,lower(trim(p.pattern)) HAVING count(*) > 1""",
        'example': """SELECT s.lexeme_id AS word_id,
                lower(trim(e.russian)) || ' / ' || lower(trim(e.english)) AS repeated_text,
                count(*) AS copies, group_concat(e.id) AS row_ids
                FROM examples e JOIN senses s ON s.id=e.sense_id
                WHERE e.active=1 AND s.active=1
                GROUP BY e.sense_id,lower(trim(e.russian)),lower(trim(e.english))
                HAVING count(*)>1""",
    }.items():
        repeats[kind] = rows(db, sql)
    repeated_content = []
    for kind, matches in repeats.items():
        for match in matches:
            word = lex_by_id.get(match['word_id'], {})
            repeated_content.append({
                'kind': kind, 'word_id': match['word_id'],
                'lemma': word.get('lemma','?'), 'pos': word.get('pos','?'),
                'copies': match['copies'], 'row_ids': match['row_ids'],
                'repeated_text': match['repeated_text'],
            })
    csv_write(out/'repeated_content.csv', repeated_content,
              ['kind','word_id','lemma','pos','copies','row_ids','repeated_text'])

    missing_senses = [r for r in lexemes if r['human_status']=='kept' and r['senses']==0]
    missing_examples = rows(db, """SELECT l.id AS word_id,l.lemma,l.pos,s.id AS sense_id,
        s.meaning FROM senses s JOIN lexemes l ON l.id=s.lexeme_id
        LEFT JOIN examples e ON e.sense_id=s.id AND e.active=1
        WHERE s.active=1 AND l.human_status='kept'
        GROUP BY s.id HAVING count(e.id)=0 ORDER BY l.lemma""")
    empty_example_fields = rows(db, """SELECT l.id AS word_id,l.lemma,l.pos,
        s.id AS sense_id,e.id AS example_id,e.russian,e.english
        FROM examples e JOIN senses s ON e.sense_id=s.id JOIN lexemes l ON l.id=s.lexeme_id
        WHERE e.active=1 AND (trim(e.russian)='' OR trim(e.english)='')""")
    expression_without_parts = []
    if 'expression_components' in tables:
        expression_without_parts = rows(db, """SELECT l.id AS word_id,l.lemma,l.pos,
            count(c.id) AS component_count FROM lexemes l
            LEFT JOIN expression_components c ON c.expression_id=l.id
            WHERE l.entry_type='expression' AND l.human_status='kept'
            GROUP BY l.id HAVING component_count<2""")
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    foreign_keys = rows(db,'PRAGMA foreign_key_check')
    csv_write(out/'missing_senses.csv', missing_senses,
              ['id','lemma','pos','entry_type','human_status','aspect','animacy','senses'])
    csv_write(out/'missing_examples.csv', missing_examples,
              ['word_id','lemma','pos','sense_id','meaning'])
    csv_write(out/'empty_example_fields.csv', empty_example_fields,
              ['word_id','lemma','pos','sense_id','example_id','russian','english'])
    csv_write(out/'expressions_missing_components.csv', expression_without_parts,
              ['word_id','lemma','pos','component_count'])

    risk = defaultdict(list)
    for group in repeated_links:
        for key in ('word_a_id','word_b_id'):
            risk[group[key]].append('repeated relationship')
    for group in repeated_content:
        risk[group['word_id']].append('repeated '+group['kind'])
    for record in missing_senses:
        risk[record['id']].append('no active senses')
    for record in missing_examples:
        risk[record['word_id']].append('sense without example')
    for record in expression_without_parts:
        risk[record['word_id']].append('expression has fewer than 2 components')
    for record in lexemes:
        if record['senses'] > 6:
            risk[record['id']].append('many senses')

    candidates = [r for r in lexemes if r['human_status']=='kept']
    rng = random.Random(seed)
    rng.shuffle(candidates)
    sample_size = max(0, min(sample_size, len(candidates)))
    selected = []
    used = set()

    def choose(pool, quota):
        for word in pool:
            if len(selected)>=sample_size or quota<=0:
                break
            if word['id'] not in used:
                used.add(word['id'])
                selected.append(word)
                quota -= 1

    if sample_size:
        # One-third issue-driven, one-third expressions/verbs, remainder random.
        flagged = sorted((r for r in candidates if risk.get(r['id'])),
                         key=lambda r: (-len(risk[r['id']]),r['id']))
        choose(flagged, max(1,sample_size//3))
        choose([r for r in candidates if r['entry_type']=='expression'], sample_size//6)
        choose([r for r in candidates if r['pos'] in ('VERB','INFN')], sample_size//6)
        # Fill from every part of speech, then randomly from all remaining entries.
        kinds = defaultdict(list)
        for row in candidates:
            kinds[(row['entry_type'],row['pos'])].append(row)
        for key in sorted(kinds):
            choose(kinds[key], max(1,sample_size//max(1,len(kinds)*3)))
        choose(candidates, sample_size)

    worksheet = [{
        'word_id': r['id'], 'lemma': r['lemma'], 'pos': r['pos'],
        'entry_type': r['entry_type'], 'senses': r['senses'],
        'reason_to_review': '; '.join(sorted(set(risk[r['id']]))) or 'random/stratified sample',
        'sense_quality': '', 'examples_quality': '', 'government_patterns': '',
        'relationships_quality': '', 'source_support': '',
        'overall': '', 'notes': ''
    } for r in selected]
    csv_write(out/'review_sample.csv', worksheet, ['word_id','lemma','pos','entry_type',
        'senses','reason_to_review','sense_quality','examples_quality',
        'government_patterns','relationships_quality','source_support','overall','notes'])

    by_type = Counter(r['relation_type'] for r in relation_records)
    repeated_type = Counter(r['relation_type'] for r in repeated_links)
    lines = [
        '# Russian Lexicon — read-only audit',
        f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        '', '## Coverage',
        f'- Lexemes: **{len(lexemes)}** ({sum(r["entry_type"]=="expression" for r in lexemes)} expressions)',
        f'- Kept entries: **{len(candidates)}**',
        f'- Active senses: **{sum(r["senses"] for r in lexemes)}**',
        f'- Examples: **{count(db,"examples")}**; patterns: **{count(db,"patterns")}**',
        f'- Relationship rows: **{len(relation_records)}**',
        f'- SQLite integrity: **{integrity}**; foreign key violations: **{len(foreign_keys)}**',
        '', '## Structural review queues',
        f'- Repeated relationship groups: **{len(repeated_links)}**, extra rows: **{duplicate_extras}**',
        f'- Repeated aspect-pair groups: **{repeated_type["aspect_pair"]}**',
        f'- Aspect pair consistency conflicts: **{len(aspect_issues)}**',
        f'- Identical meaning duplicates: **{len(repeats["sense"])}** groups',
        f'- Identical pattern duplicates: **{len(repeats["pattern"])}** groups',
        f'- Identical example duplicates: **{len(repeats["example"])}** groups',
        f'- Kept entries with no active senses: **{len(missing_senses)}**',
        f'- Active senses without an example: **{len(missing_examples)}**',
        f'- Empty Russian or English example fields: **{len(empty_example_fields)}**',
        f'- Kept expressions with fewer than 2 components: **{len(expression_without_parts)}**',
        '', '## Relationship types',
        *[f'- {typ}: {cnt} rows' for typ,cnt in sorted(by_type.items())],
        '', '## Top repeated connections',
        *[f'- **{r["word_a"]} ↔ {r["word_b"]}** ({r["relation_type"]}): '
          f'{r["rows"]} rows; sense IDs: {r["source_sense_ids"]}'
          for r in sorted(repeated_links,key=lambda x:-x['rows'])[:20]],
        '', '## Files to inspect',
        '- `repeated_relationships.csv` — same endpoints/type shown more than once; review sense scope.',
        '- `aspect_pair_conflicts.csv` — pairs that do not connect imperfective ↔ perfective.',
        '- `repeated_content.csv` — exact duplicated senses, examples, and patterns.',
        '- `missing_senses.csv`, `missing_examples.csv`, `empty_example_fields.csv` — coverage problems.',
        '- `expressions_missing_components.csv` — expression linking problems.',
        '- `review_sample.csv` — reproducible manual-review worksheet (fill in quality columns).',
        '', '### Interpretation',
        'This is a **structural** audit. It cannot establish whether Russian senses, translations,',
        'examples, government patterns, or aspect pairs are linguistically correct.',
        'Do not automatically delete non-aspect relationships: distinct sense-specific links',
        'can be legitimate. Treat all rows as review candidates, not authoritative errors.',
        ''
    ]
    (out/'audit_summary.md').write_text('\n'.join(lines),encoding='utf-8')
    return {'lexemes':len(lexemes),'relations':len(relation_records),
            'repeated_groups':len(repeated_links),'surplus_rows':duplicate_extras,
            'aspect_groups':repeated_type['aspect_pair'],
            'missing_senses':len(missing_senses),'review_sample':len(worksheet),
            'integrity':integrity,'foreign_key_violations':len(foreign_keys)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True,type=Path,help='Enriched or live lexicon database path')
    p.add_argument('--out',type=Path,default=Path('lexicon-audit-report'))
    p.add_argument('--sample-size',type=int,default=150)
    p.add_argument('--seed',type=int,default=20261122)
    a=p.parse_args()
    with connect_read_only(a.db) as db:
        summary=make_audit(db,a.out,a.sample_size,a.seed)
    print(f"Audit report: {a.out.resolve() / 'audit_summary.md'}")
    for key,value in summary.items():
        print(f'  {key.replace("_"," ")}: {value}')
    print('Read-only. No database records were modified.')

if __name__=='__main__':
    main()
