# Ruslex — Russian Lexicon

A **new, standalone application** rebuilt from the supplied v3 source and SQLite dictionary. Written with Django 5.2, Svelte 5, Tailwind 4, daisyUI 5, and Docker Compose. **No dependency on any previous v4 installation.**

## First installation on the VPS

The default path is `/srv/apps/ruslex`; persistent data is at `/srv/data/ruslex`.

```bash
# Extract the archive so /srv/apps/ruslex/README.md exists.
cd /srv/apps/ruslex
./deploy.sh --dry-run   # inspect the plan
./deploy.sh             # install and start
./manage.sh admin       # create your first Django administrator
./manage.sh test        # regression tests on disposable database copies
```

The new public hostname is **https://ruslex.2-29-159-213.sslip.io**. The local preview address is `http://127.0.0.1:8790`. The installer adds a new, independent Caddy site **only if the documented `/srv/proxy/config/sites` layout is detected**. Otherwise it prints the required Caddy block and leaves the proxy alone.

Existing v3 and former v4 services, checkouts, hostnames, and databases are never touched by this installer. You can remove old v4 separately at your discretion.

## Database separation

| Data | Host path | Django alias |
|---|---|---|
| Lexemes, senses, tags, examples, pages, occurrences, review state and relations | `/srv/data/ruslex/lexicon/lexicon.db` | `lexicon` |
| User accounts, passwords, groups, permissions, sessions, migrations, site settings | `/srv/data/ruslex/admin/admin.sqlite3` | `default` |

The first installation copies `data/lexicon.db` using SQLite's backup API. Subsequent installations **never overwrite the installed lexicon database**. Dictionary models explicitly have `managed=False`; Django migrations are routed exclusively to the administrative database. The original linguistic IDs and all sense-specific relationships remain intact.

## Common commands

```bash
./manage.sh status
./manage.sh logs
./manage.sh check
./manage.sh backup
./manage.sh test
./manage.sh update
./manage.sh admin
./manage.sh stop
./manage.sh start
```

All authenticated users start with no editor or reviewer rights. In Django Admin, open **Users** to assign one or more permission groups. Under **Site options**, enable or disable public signup (disabled by default). The three groups are **Reviewer**, **Editor**, and **Pipeline Operator**. They use backend permissions, not just hidden frontend controls.

## Technology and structure

- `backend/siteconf/`: Django settings, URLs, WSGI, database router.
- `backend/accounts/`: native Django sessions, registration switch, groups and user administration.
- `backend/dictionary/`: existing SQLite models, queries, input validation, editing services and HTTP endpoints.
- `frontend/src/pages/`: Svelte pages for search, entry editing, references, review, new words, login and statistics.
- `frontend/src/components/`: reusable sense, relation, record and word-picker components.
- `processing/`: independent offline enrichment and audit modules sourced from the provided v3 workflow.
- `scripts/`: first-install, backups, preflight and disposable database smoke tests.
- `docs/`: VPS operations reference, architecture, schema, migration, AI pipeline and limitations.

Django serves API and built Svelte assets via Gunicorn and WhiteNoise. Caddy handles HTTPS and proxies to `ruslex-web:8000` on the existing `proxy` Docker network. **No Node server, Redis, PostgreSQL, or Celery daemon runs in production.**

## IMPORTANT — verification status

The supplied dictionary passed SQLite integrity and foreign-key checks. The Python code compiled, the original search logic passed 18 recorded v3 query comparisons, and the offline processing snapshot/inventory/dry-run/audit paths executed successfully. The Svelte/TypeScript syntax was parsed and checked with the available compiler. **This environment does not have Django, Svelte's npm dependencies or Docker installed**, so the actual `npm run check`, Django integration tests, full image build and browser interactions **still must be run on your VPS**. The deployment builds/validates the image and verifies the health endpoint, and `./manage.sh test` performs disposable database API checks. Do **not** declare production parity until the remaining tests and manual workflow review pass.

Start with [docs/INSTALL.md](docs/INSTALL.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
