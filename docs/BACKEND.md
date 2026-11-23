# Ruslex backend — developer guide

This backend is intentionally a **small Django application**, not a new
abstraction layer. Keep the existing SQLite schema, HTTP paths, response keys,
permissions, and transaction boundaries stable unless a feature explicitly
requires changing them.

## Request lifecycle

```text
Svelte frontend
      |
      v
siteconf/urls.py
      |
      +--> accounts/api.py            session authentication, CSRF, signup
      |
      +--> dictionary/api.py          parse JSON, authorize, map errors
                   |
                   +--> queries.py     read-only search and serialization
                   |
                   +--> services.py    transactional dictionary writes
                              |
                              +--> validation.py  pure input validation
                              |
                              +--> models.py      unmanaged v3 tables
```

- **`dictionary/api.py`**: HTTP handlers should be short. Check method and
  permissions, pass validated JSON to the relevant operation, and return a
  response using `respond`. `api_errors` handles expected client mistakes
  (400), absent records (404), and database constraints (409). Let unexpected
  errors reach Django's normal 500 handler so they remain debuggable.
- **`dictionary/validation.py`**: Python-only, deterministic input rules.
  Functions raise `BadRequest` for invalid payloads. This module deliberately
  imports neither Django nor SQLite. Do not use model queries here.
- **`dictionary/services.py`**: Each public mutation has
  `@transaction.atomic(using="lexicon")`. Keep relationship and ownership
  checks in this layer, not in Svelte. Check ownership before updating or
  deleting a child record. The `_relation_endpoints` helper preserves
  directional *derivation* edges when edited from their incoming side.
- **`dictionary/queries.py`**: Stable import surface for HTTP handlers, plus
  books, reference browsing, tags, statistics, and review navigation.
- **`dictionary/query_search.py`**: Search filters, relevance ranking, and
  results preview formatting; same-sense tag filtering remains explicit.
- **`dictionary/query_detail.py`**: Full-entry serialization, including senses,
  relationships, components, and reference samples.
- **`dictionary/query_helpers.py`**: Bounded batches and parameterized SQL for
  legacy join tables; SQL column names come only from an allowlist.
- **`dictionary/search_rank.py`**: Stable Unicode-aware relevance tiers. The
  v3 search fixtures protect result ordering; don't alter scoring as part of a
  formatting cleanup.
- **`accounts/api.py`**: Django sessions and groups; no custom password/session
  handling and no user credentials in logs.

## Privacy and permissions

- Dictionary **entry notes are public** (including anonymous entry views).
- Relationship and expression-component editing notes remain private to
  authenticated users, matching the existing API behavior.
- Hidden entries are not visible to anonymous readers and cannot be retrieved
  indirectly through the public reference endpoints.
- A Reviewer can change only `human_status`; an Editor can modify linguistic
  content. These checks are server-side.
- Every mutating request is protected by Django's existing CSRF middleware.
  Never bypass CSRF checks to make client code work.

## Databases

`default` is the Django administration database. `lexicon` contains the
existing dictionary. No migrations, model-managed table creation, or schema
changes are needed for this refactor. Never point a dictionary transaction at
`default`.

## Testing

### Pure Python tests (no Django or Docker)

From the repository root, with Python 3.10+:

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Search-parity and historical snapshot checks require the optional local
`data/lexicon.db` fixture (not committed to Git). On the VPS, avoid copying
the live lexicon into your checkout casually. The **validation-only** test
works without that fixture:

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_backend_validation.py' -v
```

### Disposable integration tests (Django and Docker)

On the VPS:

```bash
cd /srv/apps/ruslex
./manage.sh test
```

The smoke runner creates a **temporary backup** of the lexicon and a fresh
admin database; it never writes to the mounted live databases. It checks CSRF,
permissions, hidden-entry visibility, public/private notes, search parity,
validations, tags, sense-specific examples, external links, and incoming
relationship direction.

### Before deployment

```bash
# With your local/working-tree changes already applied:
git diff --check
python3 -m compileall -q backend scripts tests
# Build before restarting; this also invokes Svelte checks:
docker compose build web
./manage.sh test
```

**Always back up persistent data before deploying** and restart only after
checks succeed. For a larger schema or API change, add an integration test
before introducing the change.

## Debugging and logging

- Expected validation errors are returned as `{"detail": "..."}` without a
  traceback. Unexpected exceptions are not silently swallowed.
- Database constraint conflicts are logged at WARNING level with the request
  path; credentials, tokens, and request bodies are **not** included.
- Django's normal exception logging remains active. Logs are written to the
  container's standard output; use `./manage.sh logs` to inspect them.
- Prefer descriptive function and variable names to additional framework or
  service layers. Extract a helper only when it has a clear responsibility or
  enables meaningful testing.

## Example: adding a new editing field

1. Confirm the field belongs in the existing database schema; don't assume a
   new column can be added without a migration plan.
2. Add its input rule in `validation.py` (or the service's domain checks).
3. Add the write in `services.py`, inside the existing lexicon transaction.
4. Expose the value in `queries.py` without changing unrelated response keys.
5. Add a malformed-input test and an integration test, then rebuild.
