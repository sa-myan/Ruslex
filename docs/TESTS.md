# Validation and test strategy

## Lightweight checks on the VPS

```bash
cd /srv/apps/ruslex
python3 scripts/offline_checks.py
./manage.sh build    # runs Svelte type check and Vite compilation
./manage.sh test     # Django smoke tests in a networkless read-only container
./manage.sh health
```

`python3 scripts/offline_checks.py` uses only Python stdlib, including the
new OCR/append-only-promotion safety tests, so it can run before building the
processing image. The processing container contains `pymorphy3` for real OCR
imports, not required by the fake-analyzer safety tests.

`./manage.sh test` uses a separate admin DB and a copy of the live lexicon.
It cannot write to the production DB: the container mounts only the source
lexicon read-only, has no access to admin.db/processing/reference, and creates
both test databases in ephemeral /tmp. The full frontend Vitest suite now runs
in CI alongside Svelte checks and the build. A separate CI job runs the
Django smoke tests against a seeded, disposable lexicon with abbreviations,
pronunciation review and inflection schemas enabled. Browser checks still needed: search,
sense editing, public notes, tags, relations, hidden words, save messages,
login, and portrait navigation.

## Highest-risk workflow validation

Before processing a **real second book**, use a small 1–3 page OCR export to
verify: `inspect-ocr`, `workspace`, `import-ocr`, `resolve --dry-run`,
`resolve --max-batches 1`, `review-forms`, `plan`, and checked DB promotion.
Actual model output shape and provider authentication could not be validated
in the offline authoring environment; this requires a **VPS trial**.

Also test a stale workspace after editing an entry on the website: `plan`
should refuse promotion. The offline unit tests cover this case.

## Future comprehensive tests

Keep the existing v3 regression tests as behavioral references. Once this
workflow is stable, extend Django/Svelte tests to cover end-to-end editing,
relational directionality, repeated imports, partial AI jobs, more complex
OCR formats, Caddy publication and disaster recovery.
