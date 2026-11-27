# Productive constructions: separate reference and historical audit

Ruslex stores productive Russian grammatical/discourse patterns separately from
ordinary lexical expressions and sense-specific government. Existing expressions
and textbook pages remain intact.

## What exists

- `constructions` holds canonical abstract patterns, English meanings,
  grammatical explanations, human review status and notes.
- `construction_examples` holds teaching sentences.
- `construction_attestations` links verbatim surface evidence to saved textbook
  pages; `construction_expression_links` links compatible constructions to
  existing expressions **without removing or reclassifying them**.
- `/constructions` is a separate reference page with search, source evidence
  and ordinary human review controls.

## Historical audit of previously imported textbooks

Run the first command after deploying the branch and backing up the dictionary:

```sh
./process.sh constructions init --confirm
```

The migration is backed up, optional, and idempotent. A scan never requires
the schema migration because it operates on an isolated snapshot.

Discover stored book titles and choose the exact one. If a title exists in more
than one edition, the command refuses the ambiguous selection.

```sh
./process.sh inventory
./process.sh constructions pages --book 'YOUR BOOK TITLE' --limit 20
./process.sh constructions pages --book 'YOUR BOOK TITLE' --contains 'чем'
./process.sh constructions scan old_book_constructions --book 'YOUR BOOK TITLE' --model 'provider/model-id' --dry-run
./process.sh constructions scan old_book_constructions --book 'YOUR BOOK TITLE' --model 'provider/model-id' --kind pages --max-batches 1
./process.sh constructions plan old_book_constructions
```

To **target a known grammar page without scanning hundreds of pages**, supply
`--kind pages --first-page N --last-page M` (inclusive **physical PDF**
page numbers from the `pages` preview). The page range must be fixed for
the workspace: a changed range requires a new workspace name. The page
preview reads saved OCR only, never invokes AI or writes a database.

Use `--kind pages` for the initial real-textbook test, `--kind expressions`
to audit existing expressions independently, or `--kind all` for both
(the default). Page-only batches no longer wait behind expressions.

**Important:** the first trial of `oldbook_constructions` used a less
selective classification prompt and produced questionable proposals for
`а вы` and `а вот`. That workspace is retained for inspection but MUST NOT
be resumed or approved: the audit rules are versioned and old scans are
explicitly blocked from promotion. Create a **new workspace name** (for
example `oldbook_pages_v2`) for the stricter audit.

If the first model batch is satisfactory, resume with the **same** book, model
and `--kind` value. Omit `--max-batches` to finish; partial validated batches
from the same rules version are reused.
To audit every imported textbook, omit `--book` when starting a **new**
workspace. Models receive saved Markdown fragments (including grammar and
exercise pages) and existing expression lemmas/meanings; they receive neither
live database write access nor OpenRussian data.

The plan consolidates identical canonical patterns and preserves all recorded
page evidence and expression links. Its `expression_review` section shows
the classification for **each historical expression** (expression-only,
construction, both, or uncertain), not merely aggregated totals. Read the
report carefully: AI confidence alone does not authorize insertion. Review
proposed meaning, pattern generalization, grammatical constraints and actual
textbook occurrences.

To approve **only specific proposed IDs**:

```sh
./process.sh constructions plan old_book_constructions
./manage.sh backup
./process.sh constructions apply old_book_constructions --approve 1,3,8 --confirm
```

Only the network-disabled promoter can write to the live lexicon. Approval
validates saved attestations against *current* textbook text and expression
identity, takes a fresh backup, inserts standalone construction records and
links, and runs SQLite integrity checks. Existing expression rows, senses,
source pages and review statuses are never rewritten. Re-applying the same
proposal IDs is idempotent. Newly inserted constructions start as **followup**,
so they are available for human review in the Constructions page.

If an existing expression is clearly **construction-only**, first approve its
construction (so its identity, evidence and source link remain preserved), then
use the normal expression review workflow to hide the redundant expression if
you wish. **Both** means keep the expression visible as well as the construction.
An uncertain classification requires manual investigation, not an automatic
migration or deletion.

For future books, use the same command after a real textbook has been promoted
or run it against a disposable rehearsal lexicon. Do **not** promote throwaway
textbook samples into the actual dictionary: the scan is available separately.

## Current limitations

- The historical scan uses an LLM: quality and costs depend on the selected
  model and saved textbook content. The provider must be tested with one batch.
- Attestation matching validates real text but cannot itself prove that an
  abstract generalization is linguistically correct. Human approval is required.
- Canonical pattern deduplication is exact after whitespace/case normalization,
  not full semantic paraphrase matching. Closely related proposals should be
  consolidated manually before approval.
- The first release uses an offline CLI for proposal approval; the web UI is
  for browsing and reviewing the **approved records**. It deliberately does
  not expose model-authored proposals via unauthenticated HTTP endpoints.
- Editing canonical patterns and associating multiple meanings directly from
  the UI are later enhancements. No automatic deletion/reclassification of
  original expressions is supported.
