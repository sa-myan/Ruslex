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
./process.sh constructions scan old_book_constructions --book 'YOUR BOOK TITLE' --model 'provider/model-id' --dry-run
./process.sh constructions scan old_book_constructions --book 'YOUR BOOK TITLE' --model 'provider/model-id' --max-batches 1
./process.sh constructions plan old_book_constructions
```

If the first model batch is satisfactory, resume with the **same** book and
model. Omit `--max-batches` to finish; partial validated batches are reused.
To audit every imported textbook, omit `--book` when starting a **new**
workspace. Models receive saved Markdown fragments (including grammar and
exercise pages) and existing expression lemmas/meanings; they receive neither
live database write access nor OpenRussian data.

The plan consolidates identical canonical patterns and preserves all recorded
page evidence and expression links. Read the report carefully: AI confidence
alone does not authorize insertion. Review proposed meaning, pattern
generalization, grammatical constraints and actual textbook occurrences.

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
