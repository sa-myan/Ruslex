# Ruslex v2: safe combined production release

This is the single operational checklist for the pronunciation backlog, new
abbreviation category, morphological paradigms, progress reporting, and the
one-workspace book importer. Run commands via SSH on the VPS as the deploy
user. **Do not skip the numbered gates or run the production mutation
commands while the app is being edited.**

The PR must pass its GitHub jobs AND the disposable full-stack rehearsal
before merging. All 43 saved OpenCode decisions are staged under
`/srv/data/ruslex/processing/stress_ai/stress43_trial2`; no model rerun is
needed. The existing production headwords and senses are the ultimate
authority.

## 0. Pre-release checks — no writes to live data

~~~sh
cd /srv/apps/ruslex-book-v2
git fetch origin
git checkout --detach origin/feat/stress-ai-exception-pipeline
sh scripts/verify_book_pipeline.sh

export PROCESSING_IMAGE=ruslex-book-check-processing:local
./process.sh stress ai-plan stress43_trial2
./process.sh abbreviations plan
./process.sh abbreviations rehearse
./process.sh forms rehearse
~~~

Required: all tests and Django smoke checks pass, the stress run reports
43/43 completed, the abbreviation plan identifies `мгу` (ID 306) only,
and rehearsals report `production_modified: false`. Stop if any result
differs. Do not run `ai-run` again: all its decisions were already stored.

## 1. Verify the proposed one-shot pronunciation approval

14 proposals select OpenRussian readings, and 20 are suggestions without
an independently documented source. The latter are **not automatically
verified** simply because the model assigned high confidence. Independently
check them (especially proper names, compounds, particle expressions and ё)
before accepting the list below. Five abstentions plus four deliberately
withheld proposals make up the excluded nine:

- 306 `МГУ`: reclassify to abbreviation; do not invent stress
- 317 `санкт-петербургский`: inspect secondary stress convention
- 724 `пинг-понг`: inspect compound secondary stress
- 806 `китайка`: verify meaning and usage classification
- 1126 `жить-быть`: inspect as potential expression
- 1146 `марта`: restore missing meaning and resolve name vs month
- 1385 `художник-модельер`: inspect multi-part stress
- 1402 `глухость`: confirm `глу́хость` against a reliable reference
- 1447 `лицо-обладатель`: inspect as possible explanatory label

Set the exact proposed approvals and preview the transaction **without
writing to the live dictionary**:

~~~sh
APPROVE=21,93,127,338,424,457,468,523,544,640,701,718,735,746,749,753,763,919,937,970,978,989,1187,1230,1290,1405,1412,1413,1416,1417,1435,1443,1457,1578
./process.sh stress ai-approval-plan stress43_trial2 --approve "$APPROVE"
~~~

Expected: **34 selected, 14 OpenRussian-backed, 20 explicitly human
approved without an exact source, nine excluded**, including ID 306. If a
reading fails independent linguistic review, remove its ID from APPROVE
**before** the live application. The final review and human approval must be
deliberate; the model alone does not authorize production updates.

## 2. Merge and prepare production code

After the dry runs and approval preflight pass, merge PR #7 through the normal
GitHub review process. **Do not deploy directly from the feature worktree.**
Then in the existing production checkout:

~~~sh
cd /srv/apps/ruslex
git status --short                  # stop if not clean
git pull --ff-only
./manage.sh doctor
./manage.sh backup                  # save BOTH lexicon and admin SQLite files
./process.sh build                  # build current processing image from main
./process.sh stress ai-approval-plan stress43_trial2 --approve "$APPROVE"
~~~

The saved run remains valid until the underlying pronunciation evidence,
dictionary headwords/senses, or reference dataset changes. Do not manually
edit a covered entry between this check and the next step.

## 3. One-time stress promotion — before all other live edits

~~~sh
./process.sh stress ai-apply stress43_trial2 --confirm --approve "$APPROVE"
./process.sh stress diagnose
~~~

Expected insertion count is the approved subset (normally **34**, unless
some records were already filled), with a timestamped additional SQLite
backup. This operation is **one transaction**. After it completes, the
`stress43_trial2` report becomes stale by design, so do not rerun
`ai-plan` or `ai-apply` against it. The remaining headwords are treated
separately. If the command fails, stop and inspect its error/backup, rather
than forcing a second application.

## 4. Stop the old web image and install the dictionary extensions

The old frontend does not know the abbreviation type. Briefly stop Ruslex
web before changing its live schema; **do not unpublish or restart Caddy**.

~~~sh
./manage.sh stop
./manage.sh backup
./process.sh abbreviations init --confirm
./process.sh abbreviations categorize --confirm
./process.sh abbreviations plan
./process.sh forms init --confirm
./process.sh forms backfill --confirm
./process.sh forms plan
~~~

Expected: `мгу` becomes the **one** newly reclassified abbreviation;
no historical word-heading false positives; forms backfill creates
approximately 35,000 inflected spelling rows based on the actual dictionary
at execution time. An additional backup precedes each DB mutation.
The form generation is deterministic/idempotent and does not claim that
generated inflections were attested in OCR or have verified stress.

Do not start new OCR imports before both schema migrations have succeeded.

## 5. Deploy and verify the combined release

~~~sh
./manage.sh deploy
./manage.sh status
./manage.sh health
./manage.sh check
./process.sh stress diagnose
./process.sh forms plan
./process.sh abbreviations plan
~~~

`deploy` builds the new web image, backups both databases, migrates only
the Django admin DB, and checks the web health endpoint. It does not replace
the lexicon. Verify manually in the browser that:
- `МГУ` appears as an abbreviation rather than an ordinary stressless word
- `писа́ть`, `паде́ж`, `соверше́нный` retain their meaning-specific stress
- inflected forms appear for normal words, and exact-form search works
- `вуз` is lexicalized and can decline, while `МГУ` does not acquire
  fabricated forms
- review, editing, expression components, and source-page links still work

If the new frontend fails, use the repo's documented deploy/rollback
process, **not** an in-place reversal of the lexicon schema. Restoring a
pre-migration DB is destructive and requires the app stopped, preserving
any edits that happened after the backup. See `docs/OPERATIONS.md`.

## 6. Finish the outstanding pronunciation cases via the editor

After the bulk import, the only expected unresolved items are the withheld
headwords (eight after `МГУ` is excluded). Check `stress diagnose`; do not
assume zero unresolved merely because most of the original 43 were reviewed.
Edit genuine dictionary entries, repair missing senses, and enter only
independently checked pronunciations in the website. Compounds may carry
secondary stress and must not be forced into the single-stress field.
Hide an OCR artifact only when the headword itself is not a real lexical
entry; hiding is logical deletion and affects all import/audit workflows.

## 7. Normal workflow for every future textbook

~~~sh
cd /srv/apps/ruslex
./manage.sh health
./manage.sh backup
./process.sh book-start book4 --input /ocr/book4.zip --book 'Book Four'
./process.sh book-run book4 --model 'openai/gpt-6.2-sol' --max-batches 1
./process.sh book-run book4             # resumes stored model/settings
./process.sh book-status book4 --book 'Book Four'
./process.sh plan book4
./process.sh book-promote book4 --confirm
./process.sh stress diagnose
~~~

Only promote when the planned new lexical entries, abbreviations, senses,
and examples make sense. The first AI run is a small quality trial; further
runs are incremental. All AI stages stream live progress and preserve
completed batches when interrupted. Existing human-curated records are
immutable to the book promoter. New headwords acquire source-backed stress
and safe forms where supported, and pronunciation exceptions can use a
book-specific AI pass (same strict approval process). Use a NEW workspace
name for every book or distinct OCR edition.

**Important limitations:** uncertain OCR forms are not silently admitted;
secondary compound stress and universally stressed inflected paradigms are
not generated; the book pipeline does not eliminate the need for spot audits.
An interrupted promotion or stale baseline must be inspected, not forced.

## 8. Ongoing maintenance

After each import: run `book-status`, inspect the audit, sample ambiguous
morphological/AI decisions, then `stress diagnose`. Weekly: check free disk
space, latest database backups, and work directory growth. Monthly: test
restoring a backup into an isolated location and confirm an encrypted
off-server copy of both databases, OCR originals, and private OpenCode state
is available. Keep source/configuration in Git and API credentials out of it.
On a 2 GB VPS, run large AI batches, Docker builds, and database migrations
sequentially rather than concurrently.

### Completion criteria

- 43/43 AI cases analyzed; approved candidates promoted **once**
- ID 306 categorized as an abbreviation; all other existing headwords kept
- 8 remaining cases inspected or explicitly deferred with reasons
- forms schema installed and backfill idempotent
- GitHub jobs + full disposable rehearsal + web health checks pass
- verified backups on and off the VPS
- future book import tested end to end on a small, *new* OCR sample
