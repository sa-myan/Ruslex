# Ruslex — Russian lexicon

A personal Russian dictionary with Django 5.2, Svelte 5, SQLite and Docker
Compose. The app is standalone and reuses your existing shared Caddy proxy;
new textbooks are processed by **separate on-demand VPS commands**, never
inside a web request.

## Start here

| You want to… | Read |
| --- | --- |
| Understand the VPS, Docker, Caddy and where files live | [VPS foundations](docs/VPS_FOUNDATIONS.md) |
| Install, build, deploy or roll back the website | [Deployment](docs/DEPLOYMENT.md) |
| Import Mistral OCR, classify words, enrich, promote data | [Book processing](docs/BOOK_PROCESSING.md) |
| Back up, restore, disable, troubleshoot | [Operations](docs/OPERATIONS.md) |
| Understand code and data ownership | [Architecture](docs/ARCHITECTURE.md) |
| Run verification and tests | [Tests](docs/TESTS.md) |
| Understand general Ubuntu/Docker hosting beyond Ruslex | [Reusable VPS guide](docs/VPS_WORKFLOW.md) |

## Everyday VPS commands

```bash
cd /srv/apps/ruslex
./manage.sh status
./manage.sh logs
./manage.sh backup
./manage.sh deploy      # controlled website release; Caddy untouched
./process.sh help       # OCR/AI staging and promotion, no always-on worker
./process.sh doctor     # check processing state directory permissions
```

Public route: `https://ruslex.2-29-159-213.sslip.io` (when published and DNS
resolves). Local-only diagnosis: `http://127.0.0.1:8790` from the VPS.

## Ownership model

- `/srv/apps/ruslex`: source code and deployment definitions, tracked in Git.
- `/srv/data/ruslex/lexicon/lexicon.db`: live dictionary, **never in Git**.
- `/srv/data/ruslex/admin/admin.sqlite3`: Django authentication, **never in Git**.
- `/srv/data/ruslex/ocr`: original OCR sources, **never in Git**.
- `/srv/data/ruslex/processing`: private workspaces and AI credentials.
- `/srv/proxy`: **shared** Caddy and certificates, independent of Ruslex.

The website has one always-on container. Svelte assets are compiled during
image build; Node is not a live web service. The AI processing image is built
separately, runs only on demand, has no public port, and its promotion service
has no network. Live dictionary promotion is append-only and refuses to
replace existing manual edits.

**Verification:** Python safety checks run without Docker. A complete Svelte
build, Django integration run, Docker processing image build and a real model
batch must still be verified on the VPS before treating a release or new-book
import as operationally validated.
