# Ruslex codebase audit and verification map

This document traces application boundaries and gives a repeatable test strategy.
It describes what the code enforces, not a guarantee that a live VPS is
configured correctly. Review `docs/ARCHITECTURE.md` for detailed component
ownership and `docs/BOOK_PROCESSING.md` before importing a new book.

## Architecture walk-through

| Layer | Source | Responsibility | Key invariant |
| --- | --- | --- | --- |
| Browser | `frontend/src/pages`, `components`, `lib` | Svelte 5 navigation, search, editing and review | UI state is not permission |
| HTTP/API | `backend/dictionary/api.py`, `accounts/api.py` | Django sessions, CSRF, authorization, HTTP validation | Writes require server-side privileges |
| Dictionary | `backend/dictionary/queries.py`, `services.py`, `pronunciation.py` | Read/write legacy lexical entities and pronunciations | Auth and dictionary databases are separate |
| Database schema | `backend/dictionary/models.py`, `processing/*` | Unmanaged SQLite lexicon, independently migrated optional features | No Django auto-migration of lexicon |
| Offline import | `processing/ocr.py`, `forms.py`, `book_pipeline.py`, `workflow.py` | OCR analysis and resumable validated AI decisions | No writes to live DB from AI worker |
| Promotion | `processing/promotion.py` | Append-only import with live-baseline comparison | Network-disabled, fresh backup, single transaction |
| Reference data | `processing/openrussian.py`, `pronunciations.py`, `form_stress.py` | Conservatively matched stress and provenance | Source ambiguity is not guessed away |
| Hosting | `manage.sh`, `process.sh`, `scripts/release.py`, Compose | Website, explicit migration and Caddy deployment | No proxy restart during normal code release |

## Filesystem boundaries

The public `web` service mounts **only** `DATA_ROOT/lexicon` and
`DATA_ROOT/admin`, at the existing paths `/data/lexicon` and
`/data/admin`. It does not mount `processing/state`, OCR, OpenRussian,
backups or processing workspaces. The offline AI worker gets live lexicon
read-only; the network-disabled promoter is the only processing service with
live lexicon write access.

## Automated test matrix

- `python3 scripts/offline_checks.py`: all standard-library unit and
  regression tests, including promotion immutability, word-form logic,
  stress/ё processing, Caddy layout, release recovery and runtime mount checks.
- `npm test` (in `frontend/`): Vitest unit/component-compiler regression
  suite, now required in CI alongside Svelte type checks and Vite build.
- `python3 scripts/ci_smoke_fixture.py`: CI Django integration smoke tests,
  with a synthetic lexicon containing hidden words, senses, tags, abbreviation
  schema, stressed headwords, review queue and an inflected form. Exercises
  authentication/CSRF, permissions, search, editing, references, forms,
  pronunciation, deferrals and relationship direction.
- `./manage.sh test` on VPS: same Django smoke suite against a consistent
  **read-only source** copy of the real dictionary; no network, no admin or
  model credential mount, and no writes to live data.
- `sh scripts/verify_book_pipeline.sh`: Docker build, worker/rehearsal and
  morphology/abbreviation migration tests on disposable copies; requires VPS
  Docker, working permissions and a readable source lexicon.

## Live-only checks and limitations

CI does **not** validate actual provider connectivity, actual OCR quality,
real-world OpenRussian coverage, physical backups off the VPS, the currently
running Caddy route or a complete browser interaction against the live site.
Run a 1–3-page real OCR pilot, inspect one model batch and promotion plan before
importing a whole book. Keep user edits and live imports serialized while a
workspace awaits promotion: the promoter correctly refuses a stale baseline.

No new framework, cache, queue, permanent worker or additional database
service is needed at the current scale.
