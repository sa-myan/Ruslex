# Book ingestion and AI enrichment — complete VPS workflow

This pipeline is **separate from the public Django/Svelte website**. All commands
run on the VPS and use the second, *on-demand* Compose project defined in
`docker-compose.processing.yml`.

**Nothing here overwrites existing lexemes, senses, personal notes, relations,
reviews, or source pages.** New information is staged and promoted only after
checks. The old v3 corpus import and OCR form classification were adapted;
the unsafe replacement-style enrichment DB rebuild has been removed from the
public CLI.

## Recommended workflow: one workspace, one promotion

This supersedes the older, multi-command procedure below for **new books**.
The older commands remain available for diagnosis, exceptional correction,
or existing workspaces.

1. Place your Mistral OCR export in `/srv/data/ruslex/ocr` (ZIP, JSON,
   page folder or marked Markdown).
2. Create an isolated workspace and import the entire detected OCR page range:

   ~~~sh
   ./process.sh book-start book3 --input /ocr/book3.zip --book 'Book Three'
   ~~~

   Use `--edition`, `--first`, `--last`, or `--offset` only when the
   specific edition or page numbering needs them.

3. Process OCR forms and missing senses (AI batches are resumable):

   ~~~sh
   ./process.sh book-run book3 --model 'provider/model-id' --max-batches 1
   ./process.sh book-run book3
   ~~~

   The first invocation is a small provider trial. On later invocations
   the book title, model, verifier and expression setting are remembered.
   Continue only if the report says more work remains. Without
   `--max-batches`, the command processes all remaining batches.

   Optional: use `--verify-model 'provider/second-id'` for independent
   checks, and `--expressions` to analyze textbook pages for idioms.
   Expression scanning can be expensive, so it is opt-in.

4. Check the single final change plan and promote once:

   ~~~sh
   ./process.sh book-status book3 --book 'Book Three'
   ./process.sh plan book3
   ./process.sh book-promote book3 --confirm
   ~~~

   The promoter runs without network access, creates its own verified
   database backup, refuses changes to existing curated records, rejects
   unfinished mandatory form decisions, and promotes **only additional rows**.
   Existing reviewed words keep their senses, tags, relationships and notes.

The normal pipeline distinguishes words, abbreviations and expressions. Familiar
initialisms and dotted abbreviations are recognized during OCR; unfamiliar
uppercase strings are flagged for AI interpretation instead of being silently
added as ordinary nouns. Run the one-time abbreviation schema migration before
importing a new book (see [ABBREVIATIONS.md](ABBREVIATIONS.md)).

The normal pipeline adds senses to *newly admitted* lexemes before their
first promotion, so the historical "promote → manually mark all kept →
create a new enrichment workspace → promote again" cycle is no longer
necessary. New words remain individually reviewable after promotion.
Items that AI cannot classify may remain `needs_review`; they do not
prevent other valid textbook vocabulary from being imported.

OpenRussian automatically supplies safe stressed headwords during promotion.
Afterwards, an optional **book-scoped AI pronunciation exception pass**
can process the small number still missing or ambiguous (see below).
If the versioned form schema is installed, new words also receive
morphologically generated inflection paradigms without a second run
(see [WORD_FORMS.md](WORD_FORMS.md)).

**Development safety:** test this workflow and the forms migration using
`sh scripts/verify_book_pipeline.sh` in an isolated Git worktree before
deploying. Neither a regular web request nor the AI worker ever receives
permission to edit the live database.

---

## 0. One-time processing setup

```bash
cd /srv/apps/ruslex
./manage.sh init         # idempotent; creates /srv/data/ruslex/ocr and processing
./process.sh build       # Python morphology + OpenCode in separate image
./process.sh doctor      # verify private state directory permissions
./process.sh version     # verify OpenCode installation
./process.sh auth        # log in inside its persistent private /state directory
./process.sh inventory   # read-only live dictionary overview
./process.sh audit       # write a read-only audit report under processing/audits/
```

Do not store API credentials in Git or the public website `.env`. OpenCode
state lives on the VPS under `/srv/data/ruslex/processing/state`; protect and
back it up. The process image uses OpenCode v2.4.0; account connection, model
IDs, quotas, and billing remain provider-specific. AI **calls have not been
verified against your provider** in the development environment; do a
`--max-batches 1` trial first.

The processing worker has `/live` **read-only**, `/ocr` **read-only**, and
`/work` writable. Its only internet requirement is provider access. Only the
separate **network-disabled promoter** receives write access to `/live`.

You can also audit an isolated candidate with `./process.sh audit --workspace book2_2026`
after creating that workspace. Audit output is a Markdown summary and CSV
review queues under its `audits/` directory; the audit does **not** remove
suspected duplicates or edit any lexical record. When auditing live, results
are written to `/srv/data/ruslex/processing/audits/`.

## 1. Inspect a new OCR source (no database changes)

Place your Mistral OCR JSON, ZIP, Markdown, or per-page folder under
`/srv/data/ruslex/ocr`. For example, upload by SFTP or download directly
from a known source onto the VPS.

```bash
./process.sh inspect-ocr /ocr/book2.zip
```

Check first/last physical PDF pages and sample text. The parser supports
Mistral JSON `pages[index,markdown]`, Markdown exports, `<!-- page: N -->`
markers, and per-page folders containing `markdown.md` and metadata. It
ignores per-page headers/footers when a main Markdown body exists. It does
**not** do OCR itself or receive PDFs directly; produce OCR before this step.

**Book identity:** OCR import stores title **and edition**. Subsequent AI
commands currently select by title; they deliberately refuse ambiguous titles
shared by several editions. Use a distinct title for each imported edition if
you intend to process multiple editions of the same textbook, or extend the
CLI with edition-scoped selection before doing so. There is no silent
cross-edition processing.

`--first`, `--last`, `--offset` and `--page-shift` are intentionally explicit:

- `first/last`: the physical 1-based PDF pages to import.
- `page-shift`: added to the OCR-export page numbers when extraction started
  in the middle of a textbook.
- `offset`: physical page number minus printed textbook page number.

## 2. Make a fresh, isolated workspace

```bash
./process.sh workspace book2_2026
```

Creates `/srv/data/ruslex/processing/book2_2026/` containing:

- `baseline.db`: sealed, checksummed snapshot of the dictionary now.
- `candidate.db`: a separate writable copy for OCR and AI results.
- `manifest.json`: source reference, checksum and creation time.

No live data is changed. Each workspace is intended for **one promotion**.
Do not manually edit `baseline.db`, modify the manifest, or reuse the workspace
for later unrelated releases.

## 3. Import the selected pages into the candidate

```bash
./process.sh import-ocr book2_2026 \
  --input /ocr/book2.zip \
  --book 'Second Russian Book' --edition '2026' \
  --first 1 --last 240 --offset 8
```

The importer adds `books`, `pages`, `surface_pages`, and `reviews` only to the
candidate. `pymorphy3` generates alternative lemmas and parts of speech for
AI or human confirmation; it does **not** automatically pick the first
analysis as truth. Re-importing the same unchanged physical page is safe;
changing an already imported page is rejected (use a new edition/source).

Existing word IDs, senses, notes, and review decisions stay intact.

## 4. Resolve OCR forms using AI (resumable)

First see a free preview without a model call:

```bash
./process.sh resolve book2_2026 \
  --book 'Second Russian Book' --model 'provider/model-id' --dry-run
```

Then deliberately process a small batch:

```bash
./process.sh resolve book2_2026 \
  --book 'Second Russian Book' --model 'provider/model-id' \
  --batch-size 12 --max-batches 1
```

If results are appropriate, repeat without `--max-batches` until all
**pending** forms have decisions. The AI gets actual contexts and multiple
pymorphy3 options. It must select an allowed lemma/POS, exclude OCR debris,
or mark uncertain cases for human review. A malformed/incomplete response
aborts that batch without applying its decisions. Raw responses are saved to
`form_reviews/` for inspection.

### Inspect and correct uncertain forms

```bash
./process.sh review-forms book2_2026 --book 'Second Russian Book' --retry
./process.sh review-forms book2_2026 --book 'Second Russian Book'

# Accept a specific review ID with one of its EXISTING morphological options:
./process.sh decide-form book2_2026 --book 'Second Russian Book' \
  --id 12345 --decision admit --lemma 'книга' --pos NOUN
# Or exclude:
./process.sh decide-form book2_2026 --book 'Second Russian Book' \
  --id 12345 --decision exclude
```

The `--id` in the examples is illustrative; use an actual ID from `review-forms`.
A form marked uncertain may also remain for future review, but make a
conscious decision before promoting. New `lexeme_pages` occurrences are linked
only to admitted analyses; an existing lexeme is reused, never replaced.

### Quick progress check (any time after OCR import)

Instead of inspecting raw SQLite tables or guessing what remains, run:

```bash
./process.sh book-status book2_2026 --book 'Second Russian Book'
```

This read-only report gives page count, pending and uncertain forms,
attested lexemes, new entries and the next safe step. An uncertain form
can be deferred; pending forms cannot be promoted. Use model batches
for the routine form decisions, and manually review only unresolved cases.

### Reusable AI pronunciation exception pass

OpenRussian automatically supplies safe headword stress during ordinary
promotion; this does **not** call an LLM. After promoting the book and
adding its important senses, optionally run an AI pass on the **few
remaining unresolved pronunciations from that book**:

```bash
./process.sh stress ai-run book2_stress \
  --book 'Second Russian Book' --model 'provider/model-id' --dry-run
./process.sh stress ai-run book2_stress \
  --book 'Second Russian Book' --model 'provider/model-id' \
  --verify-model 'provider/different-model-id' \
  --batch-size 8 --max-batches 1
# Repeat the same command without --max-batches to finish.
./process.sh stress ai-plan book2_stress
```

The LLM sees each Ruslex meaning with stable sense IDs, short attested
book contexts, and *separate* source glosses for every competing reading.
Its output is strictly validated and saved in resumable batch files.
Missing-reference suggestions stay **human-review only**. Only
independently agreeing, high-confidence, source-backed homograph readings can
qualify for automatic application. With one model, validated results are
**actionable proposals**, not automatic approvals.

For the current 43-case run, finish all batches *before* reclassifying `мгу`
as an abbreviation: reclassification intentionally invalidates the old input
manifest. Inspect the decisions using `ai-plan`. A human may approve
individual IDs, including source-backed single-model decisions and
well-supported AI stress suggestions (which are not labeled as source-backed).
For example, after evaluating the complete preview:

```bash
./process.sh stress ai-plan book2_stress
./manage.sh backup
./process.sh stress ai-apply book2_stress --confirm --approve 21,93
```

Only include IDs after checking their proposed pronunciation against reliable
linguistic evidence. `--approve` is never inferred from model confidence.
The promoter rejects arbitrary IDs and incomplete AI runs, revalidates each
source ID, and rejects stale meanings or case lists. Explicitly approved
unsupported-source suggestions are stored with `source=manual`, not
`source=openrussian`. Omit `--approve` to apply only entries that meet
the strict independent-model eligibility rule.

This runs with no network, automatically creates another database backup and
rechecks live evidence. Existing pronunciation records are never replaced.
Different meanings, conflicting variants, unsupported sources and uncertain
model outputs can remain in the review queue for the normal editor.

This optional pass is a continuation of the book-processing workflow,
not a replacement for the existing form and sense validation stages.

## 5. Review the proposed changes and promote

```bash
./process.sh plan book2_2026
./manage.sh backup
./process.sh promote book2_2026 --confirm
```

Promotion independently creates a new `before-promotion-*.db` backup.
It first verifies:

1. Candidate, baseline and live schemas match.
2. Every row existing in the baseline is unchanged in the candidate.
3. Live dictionary still matches the original baseline (including your manual
   edits, user review decisions and notes).
4. No existing record has been deleted or modified.
5. Newly imported OCR forms are not still in `pending` status.
6. SQLite integrity and foreign keys pass.

Only new rows are inserted with a single live SQLite write transaction. The
promoter has **no network** and cannot call an AI provider.

**Important:** If someone edits the dictionary on the website after workspace
creation, promotion will refuse to proceed. Keep the old workspace for audit;
create a new workspace from the current live database and re-import its source.
Do not disable the live-change checks or copy a candidate DB over the live DB.

### After importing a book

Newly admitted lexemes begin **unreviewed**. Use the website's Review Mode
to mark valid words as `kept`, hide bad candidates and adjust linguistic
information. The website is your final human authority.

## 6. Enrich missing senses (optional, separate promotion)

After reviewing the imported words on the website, start a **new** workspace.
Only kept words **without senses** from the selected book will be sent to the
model. Existing manually maintained senses are left untouched.

```bash
./process.sh workspace book2_enrichment
./process.sh enrich-prepare book2_enrichment
./process.sh enrich-run book2_enrichment \
  --stage lexemes --book 'Second Russian Book' \
  --model 'provider/model-id' --dry-run
./process.sh enrich-run book2_enrichment \
  --stage lexemes --book 'Second Russian Book' \
  --model 'provider/model-id' --max-batches 1
# Repeat without --max-batches when the initial results are satisfactory.
./process.sh enrich-run book2_enrichment \
  --stage pages --book 'Second Russian Book' \
  --model 'provider/model-id' --max-batches 1
./process.sh enrich-report book2_enrichment --book 'Second Russian Book'
./process.sh enrich-apply book2_enrichment
./process.sh plan book2_enrichment
./process.sh promote book2_enrichment --confirm
```

`enrich-run` only saves *validated proposal batches*. `enrich-apply` inserts
senses only on entries that still have none, and creates genuinely new
attested expressions. It never deletes/rebuilds senses. Existing expressions
can receive new source attestations but not rewritten meanings.

Model-suggested synonym, aspect, derivation and other relationships are saved
in `enrichment_review.json` **without automatically inserting them**. Review
and add them through Ruslex's sense-specific relationship editor, which is
safer than generating incorrect directional or sense-scoped links.

**Patterns:** AI prompts use case notation where appropriate, but validation
now accepts ordinary Russian conjunction/discourse patterns (e.g. `не X, а Y`)
which do not end with a grammatical-case marker.

## 7. What happens if something fails?

| Failure | Effect / recovery |
| --- | --- |
| Model quota/timeout/invalid JSON | Current batch not applied; previous validated batches remain in workspace |
| Interrupted import | Already committed unchanged pages skip on retry |
| OCR page changed | Refuse overwrite; investigate source or create a new edition |
| Incomplete form decisions | `plan` reports pending; `promote` refuses |
| Another person edits live dictionary | `promote` refuses, never erases their work |
| Model invents expression attestation | Strict source verification rejects the batch |
| Uncertain relationship | Stored as a suggestion, not an automatic DB link |
| Deployment restarts website | Processing workspace remains on host; no connection to web lifecycle |

## 8. Security and costs

AI text is untrusted source content. The model receives selected OCR text and
is configured with denied tool permissions; it does not get database write
access. Enforced boundaries are Docker's filesystem mounts and a separate,
network-disabled promotion operation. The OpenCode configuration denies tools at both the agent-permissions and
policy levels; this is additional defense, not a substitute for filesystem
mount boundaries and a network-disabled promoter.

Workspaces and original OCR are private data; they can grow substantially.
Model use may incur charges and outbound data transfer. Do not send material
to an external AI provider unless you have the necessary rights.

Remember: **importing OCR**, **resolving word forms**, **enriching vocabulary**,
**promoting data**, **AI pronunciation exception review**, and **editing on the website**
are separate, guarded stages. The normal case follows OpenRussian automatically;
the exception stage is small, reusable and optional.

## Optional OpenRussian headword reference (no AI and no promotion)

The `./process.sh reference` command provides read-only OpenRussian
headword lookup, optional forms, verb partners, and an audit for stress/ё
candidates. It is independent of the Mistral OCR and enrichment pipelines.
The reference file lives at `/srv/data/ruslex/reference/openrussian.db`;
it is not the live dictionary. See [OPENRUSSIAN.md](OPENRUSSIAN.md).

~~~sh
./process.sh reference lookup 'читать' --forms
./process.sh reference audit
~~~

Audit CSV rows are suggestions; this stage **does not** alter Ruslex lemmas,
forms, senses, or stress. Pronunciation storage is handled by a separate versioned migration and
source-backed backfill. See [PRONUNCIATION.md](PRONUNCIATION.md).
