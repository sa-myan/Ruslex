# Architecture

## Request flow

`Browser (Svelte 5 SPA)` → `Caddy HTTPS` → `Gunicorn` → `Django native HTTP endpoints` → `SQLite lexicon or admin`.

There is only **one runtime service**: `web`. The frontend is built by Vite at image-build time, placed into Django's static directory and served by WhiteNoise; Node is not required in production.

## Backend code boundaries

- `siteconf/` — environment-backed configuration, Caddy-aware HTTPS settings and database routing.
- `accounts/` — Django users, groups, session authentication, permission checks, registration control, admin interface. No custom authentication database code.
- `dictionary/models.py` — explicit mappings of the existing v3 dictionary tables; `managed=False`.
- `dictionary/queries.py` — read-only search, references, review queue, statistics, entry serialization; includes narrowly scoped SQL for legacy tables without integer IDs.
- `dictionary/services.py` — validated mutations with `transaction.atomic(using='lexicon')` for each operation.
- `dictionary/api.py` — HTTP verbs, request parsing, authorization and responses; no SQL hidden in views.
- `processing/` — offline enrichment and auditing, outside the web request process.

Django's Group permissions are the authoritative authorization source. Anonymous browsing excludes hidden words; a user needs the Reviewer permission to see hidden words or enter Review Mode. Editors can mutate dictionary content but permission checks happen server-side.

## Frontend code boundaries

`App.svelte` owns the layout/navigation. `pages/` owns the screens; `components/` owns repeating sense and record editors. `lib/api.ts` is the only file that manages API requests, CSRF headers and session state. `lib/types.ts` contains wire types. Svelte 5 is used without the server-side rendering layer of SvelteKit.

## Data consistency

The dictionary is intentionally separate from Django's administrative database. There are no cross-file foreign keys. The dictionary tables still use their native foreign keys, and no Django schema migrations target the dictionary connection. Each write occurs in a transaction on the lexicon database. The importer backs up through SQLite's backup API, not an unsafe raw copy of an active database.

The source code never needs to know where previous v4 was installed. The new project lives at `/srv/apps/ruslex`, binds only localhost port `8790`, and uses the distinct `ruslex` Compose project and hostname. No script deletes, patches or reuses a previous v4 checkout.

## Tradeoffs

- SQLite is appropriate at the current size; many simultaneous writers may eventually justify PostgreSQL. Avoid overengineering until observed requirements demand it.
- Python relevance scoring matches recorded v3 examples and is maintainable for ~1,700 entries; if the lexicon grows much larger, consider indexed search.
- Some v3 features are tied to specialized review/enrichment scripts; the new offline pipeline deliberately remains independent of the Django web server.
