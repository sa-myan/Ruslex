# Verification and limitations

## Offline checks performed before packaging

- Python module compilation succeeded.
- 18/18 recorded v3 search relevance/count/top-result fixture comparisons passed using the bundled database.
- SQLite integrity and foreign-key checks passed; lexeme, sense and relationship counts confirmed.
- Offline processing `inventory`, `prepare`, `report` and `run --dry-run` succeeded.
- Svelte TypeScript script sections and standalone TypeScript files passed syntax parsing with TypeScript 5.8.
- Dockerfile, Compose YAML and shell scripts passed structural/syntax inspection (but not actual Docker startup).

## Must be executed on the VPS

```bash
cd /srv/apps/ruslex
./deploy.sh --dry-run
./deploy.sh
./manage.sh check
./manage.sh test
```

`./manage.sh test` creates **temporary copies** of the lexicon and a fresh admin database to verify schema routing, blocked anonymous edits, disabled signup by default, hidden entry visibility, v3 query fixture parity, reviewer/editor boundaries, and registration permission defaults. It does not write to the mounted production databases.

## Browser acceptance checklist

- Sign in and out; verify CSRF handling, Django Admin and first superuser creation.
- Search Russian and English words, check meaning ranking and multiple-page filtering.
- Toggle Review Mode and confirm hidden entries **never appear** when it is off.
- Edit a headword, create/edit/archive senses, add/edit examples and patterns.
- Create/edit sense-specific relationships from both directions; verify they appear under the correct sense.
- Assign/remove tags, add external links and expression constituents, browse textbook reference pages.
- Create a reviewer and editor through Django Admin and verify role restrictions.
- Confirm registration can be enabled and disabled by Django Admin; freshly registered users cannot edit.
- Verify backups and a restart leave both database files unchanged.

**Do not call this a fully verified production release until the entire checklist passes.** The build-time verification catches Python import and frontend compilation errors before the new container is run, but cannot replace manual browser regression testing.
