# Database contract

The packaged dictionary is a copy of the user-supplied `lexicon(1).db`, not a generated empty schema. At packaging time it contains **1,710 lexemes, 2,954 senses, 361 sense-scoped relations, and 340 source pages**. SQLite `integrity_check` and `foreign_key_check` pass.

| SQLite database | Purpose | Managed by |
|---|---|---|
| `lexicon/lexicon.db` | `lexemes`, `senses`, `examples`, `patterns`, `tags`, `sense_tags`, `books`, `pages`, `lexeme_pages`, `lexeme_relations`, `expression_components`, `external_links`, `reviews`, `surface_pages` and ancillary corpus data | Existing v3 schema; Django `managed=False` or scoped SQL |
| `admin/admin.sqlite3` | Django users, auth groups and permissions, admin, sessions, migrations, `accounts_siteoptions` | Django migrations (default database only) |

The legacy model mapping is `backend/dictionary/models.py`. The router in `backend/siteconf/router.py` sends lexicon models only to the `lexicon` alias and all Django-owned apps to `default`. It rejects migrations targeting the lexicon.

Do not flatten relations at word-pair level: a relationship can bind a particular sense on each end, and some pairs intentionally contain multiple valid links. A repeated word pair does not automatically mean a duplicate record.

For safe backups, use `./manage.sh backup`; both databases are copied independently through the SQLite backup API. For long-running AI enrichment, operate on a detached staging snapshot and explicitly promote candidate data only after auditing. Never overwrite a live SQLite file with `cp` while another process holds it open.
