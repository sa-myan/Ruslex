# Ruslex architecture and ownership boundaries

The project has **two independently started Compose projects**, sharing only
the persistent dictionary and OCR/workspace directories:

```
Internet HTTPS -> one shared Caddy -> proxy network -> ruslex-web:8000
                                                   |
                                    Django + compiled Svelte (one image)
                                                   |
                    /srv/data/ruslex/lexicon/lexicon.db
                    /srv/data/ruslex/admin/admin.sqlite3

On-demand, no Caddy route:
  ruslex-processing worker (network, /live read-only)
    -> OCR import / AI review / validated enrichment -> /work/candidate.db
    -> inspect / plan
  ruslex-processing promoter (NO network, /live read-write)
    -> live baseline comparison -> SQLite backup -> append-only transaction
```

## Backend code

- `backend/siteconf/`: Django settings, URLs, SQLite routing and WSGI.
- `backend/accounts/`: Django-auth groups, sessions and admin.
- `backend/dictionary/api.py`: request parsing, permissions, JSON responses.
- `backend/dictionary/validation.py`: request validators independent of Django.
- `backend/dictionary/services.py`: transactional editing operations.
- `backend/dictionary/queries.py`: stable read-only interface.
- `query_search.py`, `query_detail.py`, `query_helpers.py`, `search_rank.py`:
  search, entry serialization, SQL and relevance.

Dictionary models are unmanaged (`managed=False`); Django migrations are
routed only to the separate **admin** SQLite database. Existing lexeme IDs,
sense-scoped relationships, review decisions and user notes must be preserved.

## Frontend code

- `App.svelte`: application shell/page routing.
- `pages/`: one screen per file.
- `components/`: reusable entry, sense, tag, relation and navigation editors.
- `lib/http.ts`, `session.ts`, `navigation.ts`, `errors.ts`, `types.ts`: common
  transport, identity, navigation, errors, wire contracts.
- Svelte 5 runes for local component state; stores remain for global shared
  state, which is still supported by Svelte.

Vite runs at **image build time**, producing files that Django/WhiteNoise
serves. There is **no frontend Node service** on the live VPS.

## Operational code

- `Dockerfile`, `docker-compose.yml`: web image and only always-on service.
- `Dockerfile.processing`, `docker-compose.processing.yml`: on-demand isolated
  CPU/network-bound processing; promoter has no network.
- `manage.sh`, `scripts/install.py`, `release.py`, `proxy.py`, `backup.py`,
  `restore.py`: installation, release, shared-proxy publication and recovery.
- `process.sh`, `processing/cli.py`: corpus and AI command-line interface.
- `processing/ocr.py`: Mistral OCR input/page parsing, tokenization, morphology.
- `processing/forms.py`: form classification and manual decisions.
- `processing/storage.py`, `provider.py`, `prompts.py`, `validation.py`,
  `workflow.py`, `enrichment_merge.py`: vetted incremental enrichment.
- `processing/promotion.py`: sole planned entry point for inserting offline
  processing data into the live lexicon.
- `processing/audit.py`: independent read-only dictionary audit, exposed through `./process.sh audit`.
- The old unused `Pipeline Operator` group is no longer created during role initialization; any existing group remains intact for manual review.

## Data lifecycle invariants

1. Git changes code. Docker images run code. SQLite backups protect data.
2. The live lexicon is never part of the image or Git repository.
3. The website does not call an LLM or depend on OpenCode being running.
   Its container mounts only the writable `lexicon/` and `admin/` directories,
   not OpenRussian, OCR, processing workspaces, backups or AI credentials.
4. Processing must be reproducible from original OCR + a baseline snapshot.
5. AI proposals are not authoritative: new data is validated and staged.
6. Promotion is append-only, uses a fresh live-state comparison and backups,
   and performs writes inside a single SQLite transaction.
7. Human-maintained existing senses and review state are not overwritten.
8. No script modifies Caddy except the explicit `publish`/`unpublish` commands.
9. There is one shared `proxy` Docker network; removing Ruslex must not delete
   it or stop unrelated containers.

## Why this architecture (instead of more services)?

The current small SQLite dictionary and occasional OCR/AI batches don't need
PostgreSQL, Redis, Celery, Kubernetes or a permanent inference server. A
single web container and temporary processing containers are a deliberately
small operational footprint for a 2 GB VPS.

Read [VPS_FOUNDATIONS.md](VPS_FOUNDATIONS.md), [DEPLOYMENT.md](DEPLOYMENT.md),
[BOOK_PROCESSING.md](BOOK_PROCESSING.md), and [OPERATIONS.md](OPERATIONS.md).
