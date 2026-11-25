# Headword stress and ё — versioned migration

Pronunciation is **not** lexical identity. Existing lexeme IDs, lemma strings,
senses, relationships, page occurrences, review decisions and notes are never
rewritten by OpenRussian.

## Storage

`lexeme_pronunciations` stores independently editable stressed spellings,
provenance, a verification state (`source_backed`, `verified`, `disputed`),
and an optional primary display choice. Multiple readings are supported.
`sense_pronunciations` connects readings to particular meanings, enforcing
the same lexeme. Both tables are created by a separate schema migration; they
are NOT Django-owned migrations and NOT part of ordinary append-only OCR
promotion.

OpenRussian candidates remain unverified *source-backed* records until
corrected or verified by a human. Manual edits become `verified` and never
retain a misleading OpenRussian provenance reference.

## Safe VPS sequence

**Do not deploy this experimental branch to production as-is.**
First test the branch against a disposable snapshot, and run the offline
regression suite, Django checks and frontend build. Keep your production checkout on `main`. To test the feature without
switching branches in the production checkout, make a separate Git worktree:

~~~sh
cd /srv/apps/ruslex
git fetch origin
git worktree add --detach /srv/apps/ruslex-pronunciation origin/feat/headword-pronunciation-foundation
ln -s /srv/apps/ruslex/.env /srv/apps/ruslex-pronunciation/.env
cd /srv/apps/ruslex-pronunciation
~~~

From that isolated checkout, all pre-deployment checks are available in one command:

~~~sh
sh scripts/verify_pronunciation.sh
~~~

The script uses *separate test-only web and processing image tags*; it does
**not** recreate or retag the production web container/image, or write to the
live lexicon. It runs offline unit tests, the Svelte type/build check,
Django's existing copy-based smoke tests both **before and after** the stress
migration, and a complete stress init/backfill rehearsal using an independently
snapshotted SQLite database under
`/srv/data/ruslex/processing/stress_rehearsals`. The rehearsal runs with no network and no AI-credential mount, with the live
lexicon mounted read-only. It fails on integrity errors, changed legacy
record counts or non-idempotent backfill. The post-migration Django tests
also exercise editor authorization, stress corrections, meaning associations,
and public pronunciation display.


On the VPS, after the PR has been reviewed and merged, and after a normal
tested deployment, the intended one-time sequence is:

~~~sh
cd /srv/apps/ruslex
./manage.sh backup
./process.sh build
./process.sh reference info
./process.sh reference audit
./process.sh stress plan
./process.sh stress rehearse
./process.sh stress init --confirm
./process.sh stress plan
./process.sh stress backfill --confirm
./process.sh stress plan
./manage.sh check
~~~

The initial `stress plan` is read-only, even when the new schema has not
been created. `init` and `backfill` run inside the **network-disabled**
promoter (not inside the web server or AI worker); each takes an additional
consistent online SQLite backup automatically. They are idempotent on a
stable database. A second backfill does not replace or add readings to a
lexeme that already has any pronunciation record.

Source dump: `/srv/data/ruslex/reference/openrussian.db`. It is mounted
**read-only** in both worker and promoter. No source database or private
dictionary belongs in Git.

## Eligibility and audit

The lookup handles ordinary Cyrillic and hyphenated headwords, capitalization
and е/ё matching. The audit independently reports possible ё spelling
disagreements even when a word is ambiguous or contains a source warning.
Part-of-speech filtering abstains when the source type is unknown.
Unambiguous, valid, matching-POS and matching-ё candidates are marked
`safe_backfill`. The plan reports `backfill_blockers` and
`candidate_blocked_reference_types` so apparently ordinary candidates with
unknown POS labels can be inspected rather than manually accepted blindly. No ambiguous, unknown-POS or malformed reading is imported
automatically. Existing pronunciation rows are never overwritten.

New textbook lexemes are automatically checked **at promotion time**, inside
the same transaction, provided the schema is installed and the reference is
available. This does not introduce a new LLM call or inflected-form pipeline.

## Display and correction

The search API and entry details expose `stressed_lemma`; the entry detail
also exposes `pronunciations` with provenance and sense associations. If
there is no uniquely designated non-disputed primary reading, the original
lemma remains the visible fallback. The entry editor (for permitted editors)
can add a reading, choose a vowel, toggle е/ё, mark a reading primary and
associate it with senses.

Manual editing routes:

- POST `/api/lexemes/{id}/pronunciations`
- PUT and DELETE `/api/lexemes/{id}/pronunciations/{pronunciation_id}`

No public write action is allowed without the existing edit permission.

## Caveats and validation

- The real OpenRussian dump is not part of the repository. The audit must be
  rerun against the exact VPS dump before interpreting coverage counts.
- Existing unpromoted OCR workspaces were created before the schema migration.
  Recreate them from a fresh baseline before further promotion.
- The current first version supports a single stressed vowel per headword;
  unusual double-stressed compounds require a deliberate later extension.
- Updating a lemma manually does not silently rewrite existing pronunciation
  records; inspect pronunciation after changing headword spelling.
- The schema and bulk backfill are live database operations. Verify backups,
  SQLite integrity, Django endpoint behavior, the Svelte build and smoke tests
  on a **disposable database copy** before applying to production.
- OpenRussian has attribution/share-alike license obligations (CC BY-SA 4.0);
  check how those apply to the intended publication of derived readings.

## Diagnose the unresolved headwords (read-only)

After the initial source-backed import, run:

~~~sh
./process.sh stress diagnose
~~~

The isolated `rehearsal` service has no network, and mounts live SQLite and
OpenRussian read-only. The command writes a JSON diagnostic to
`$DATA_ROOT/processing/stress_diagnostics/<timestamp>/unresolved_headwords.json`.
It contains all headwords without stored pronunciations, grouped POS mismatch
counts (Ruslex POS vs. OpenRussian `type`), selected Russian/English glosses,
ambiguous readings, ё disagreements, reference warnings, and sample entries
missing from the source. The terminal output is intentionally shorter.

The diagnostic considers only active entries. Hidden entries are omitted
from headword counts, unresolved cases and all examples. The terminal
reports `active_dictionary` coverage and `missing_examples`; the JSON
contains only the active unresolved entries.

This command **does not** change matching rules or import any readings.
`other`, `expression` and mismatching known POS values remain unresolved
until there is concrete evidence that a proposed rule is linguistically safe.
The diagnostic does not send material to an LLM or require an API key.


## Active-only coverage and pronunciation consensus

Ruslex entries with `human_status='hidden'` are treated as logically
**deleted** for pronunciation work. They are excluded from audit, lookup
matching against Ruslex, coverage denominators, diagnostics and all future
OpenRussian automatic imports. Their existing database records and any
pronunciations are retained so hiding and unhiding remains reversible.

Where a valid OpenRussian headword has an unambiguous pronunciation but a
nonmatching or generic reference POS such as `other`, a second deterministic
`reference_consensus` route is available. It requires **every** matching
reference record (before any POS filtering) to have exactly one identical,
well-formed stressed spelling; it excludes ё disagreements, missing stress,
source warnings, and conflicting readings. It never rewrites Ruslex POS or
infers semantics. The regular `pos_match` route is retained. Both produce
`source_backed` provenance, not human verification.

A one-time backfill may safely add consensus readings for visible headwords
that still lack pronunciation records. Run `./process.sh stress plan` and
`./process.sh stress rehearse` first, and verify the extra number of
`reference_consensus` readings before executing the production backfill.
The existing 1,147 source-backed entries will not be rewritten, even if a
word has subsequently been hidden.
