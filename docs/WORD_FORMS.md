# Russian word forms: deterministic paradigms, not fabricated stress

Ruslex now distinguishes three different layers:

1. **Headword** — one canonical lexeme `lemma + POS`, optionally with
   independently verified stressed spelling in `lexeme_pronunciations`.
2. **Morphological paradigm** — normalized inflected spellings and grammatical
   tags from `pymorphy3`, stored in `lexeme_forms`, indexed for reverse lookup.
3. **Attestations** — actual surface spellings and their contexts/pages from
   imported books (`lexeme_pages` and `surface_pages`). Generated forms are
   **not** presented as evidence that a textbook contains them.

Abbreviations are distinct from words. A small known set of lexicalized,
inflecting abbreviations (such as `вуз`) can have generated paradigms;
ordinary initialisms such as `МГУ` have no automatically invented inflection.

This is intentionally not a full stress dictionary of every conjugated form.
We never invent inflection stress. `ё` is retained as emitted by the
morphological analyzer, and the original headword stress remains separate.
Verified irregular forms or inflected stress could be a later sourced layer.

## Safe first installation

In an isolated feature-branch worktree on the VPS, run:

~~~sh
sh scripts/verify_book_pipeline.sh
~~~

This performs offline regressions, builds separately tagged web and processing
images, creates a consistent **disposable** copy of the live database, migrates
that copy, generates forms with the actual installed `pymorphy3`, repeats the
backfill to check idempotence, then executes Django smoke tests against the
migrated copy. It does **not** change production data or restart the website.

Only after tests, PR review and a normal production web deployment:

~~~sh
./process.sh build
./process.sh forms plan
./process.sh forms rehearse
./manage.sh backup
./process.sh forms init --confirm
./process.sh forms backfill --confirm
./process.sh forms plan
./manage.sh health
~~~

The network-disabled promoter creates **additional** verified SQLite backups
before migration and backfill. The worker/rehearsal container receives read-only
access to the live lexicon. The migration is independent of Django's admin
database migrations.

Backfill deliberately abstains from:
- hidden (logically deleted) entries,
- uninflected categories and tokens,
- lexemes without a matching dictionary analysis,
- competing morphological paradigms that cannot safely be merged.

The plan lists expected headwords/forms and the skipped-reason counts. The
database schema uses source attribution (`pymorphy3` by default), a version
record, unique constraints, foreign keys and an index on folded form keys
(e/ё and stress folded for searching). Existing form records are never
automatically overwritten.

New lexemes promoted from a book receive their paradigms automatically,
**in the same guarded transaction**, once the form schema has been installed.

## Website behavior

Entry detail returns `word_forms`, and the entry page displays the
inflections with tags. Search accepts exact inflected spellings and finds
their corresponding lemmas, without suppressing direct lemma matches.
Older databases without the new table continue to work; the API returns
an empty forms array until migration.

Example: a search for `читаю` can find the lexeme `читать`, while page
references still distinguish where `читаю` was *actually encountered*.
