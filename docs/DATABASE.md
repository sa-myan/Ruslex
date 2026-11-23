# Ruslex database contract

Ruslex uses **two separate SQLite databases**. Their files are persistent data
on the VPS, **not packaged artifacts and not part of Git**.

| Host path | Meaning | Owner of schema |
| --- | --- | --- |
| `/srv/data/ruslex/lexicon/lexicon.db` | Words, senses, tags, pages, reviews, expression components, relations and source evidence | Existing v3 schema; unmanaged Django models and explicit SQL |
| `/srv/data/ruslex/admin/admin.sqlite3` | Django accounts, sessions, permissions, options and migrations | Django migrations (`default` alias) |

The original **reference snapshot** used during development contained 1,710
lexemes, 2,954 senses, 361 relationships and 340 source pages. Those counts
are *historical reference data*, not limits and not guaranteed current totals
of the live dictionary. The reference `data/lexicon.db` file, when available,
is an optional local test fixture; it must never be promoted automatically.

`backend/dictionary/models.py` maps the existing lexicon tables using
`managed=False`; `backend/siteconf/router.py` directs those operations to the
`lexicon` alias and prevents Django's migrations from modifying its schema.
The admin database uses the normal Django migration system.

Sense-scoped relationships are not equivalent to undifferentiated word-pair
relationships. Distinct sense-to-sense connections can share the same two
headwords and must not be deleted automatically.

Use `./manage.sh backup` for consistent SQLite snapshots and
`./process.sh workspace` for isolated AI/OCR workspaces. **Never copy a
running database's `.db` file to create a backup or replace the live database
with an AI candidate**. `./process.sh promote NAME --confirm` is the only
supported automatic promotion path; it preserves all existing live rows.

See [BOOK_PROCESSING.md](BOOK_PROCESSING.md) and
[OPERATIONS.md](OPERATIONS.md) for end-to-end data lifecycle procedures.
