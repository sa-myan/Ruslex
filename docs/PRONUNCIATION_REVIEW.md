# Editing and pronunciation review

Ruslex now has a single **Edit & review mode** switch in the sidebar.
Its features still honor the existing Django edit and review permissions:
enabling the visual mode does not grant permission to perform any operation.

## Pronunciation review

The **Pronunciation review** page covers active words and abbreviations
with **no verified pronunciation**. It includes entries with no reading,
OpenRussian source-backed readings, and disputed readings. A manually
verified reading removes an entry from the queue. For now, one verified
reading is sufficient: follow-up work may require separate review for
additional sense-specific readings.

Choose **Pending**, **Deferred**, or **All unresolved**. Each entry shows
its meanings, textbook excerpts, and existing pronunciation records.
Use the existing pronunciation editor to mark stress, correct е/ё,
assign sense IDs, and explicitly save. There is no automatic acceptance.

**Deferred** is a reversible private note independent of the ordinary
lexeme review status. Skip does not change any data. The review queue
does not change the human status of any dictionary entry.

Use **Jump to unresolved entry** to find an exact Russian headword (case
insensitive, preserving ё) or an entry ID such as `#123`. This searches
pending and deferred entries, switches to *All unresolved* on success, and
leaves the current entry unchanged on no match. Already verified, hidden
and expression entries are excluded. No deferrals or pronunciations change.

### OpenRussian alternatives

An optional **offline cache** shows OpenRussian headword readings,
source part-of-speech labels, English glosses and warnings, clearly
separated by reading. For meaning-distinct homographs, the user
must choose the appropriate reading using the supplied context.

The public web server **never opens the OpenRussian SQLite dump**.
The source is mounted read-only in the isolated processing container;
candidate records, with the source fingerprint, are copied into a
small editor-only SQLite cache. The display includes OpenRussian
attribution and CC BY-SA 4.0 license notice.

Clicking **Use in editor** only pre-fills the existing pronunciation
editor. It edits an existing record when the stressed spelling already
exists. Otherwise it prepares a new record. The user must still press
**Save reading**. Entries with source warnings cannot be filled via
this shortcut; independent verification and manual entry are possible.

Manual approvals are stored as verified manual readings, not falsely
attributed to a source record. Candidates are not automatically
linked to senses and never silently update other dictionary records.

## Test directly on the existing VPS without merging

Make sure the working tree is clean, and test the branch directly
on the single-user site:

```sh
cd /srv/apps/ruslex
git status --short
git fetch origin
git switch --detach origin/feat/pronunciation-review-queue

./process.sh build
./process.sh pronunciation-review plan
./process.sh pronunciation-review candidates-plan

./manage.sh backup
./process.sh pronunciation-review init --confirm
./process.sh pronunciation-review candidates-refresh --confirm
./process.sh pronunciation-review plan

./manage.sh deploy
./manage.sh health
./manage.sh check
```

The initial plans are read-only. The `init` action is idempotent
and backs up the SQLite database before adding the queue and optional
candidate tables. It also upgrades an installation from the initial
PR #9 queue version without losing deferral notes. The
`candidates-refresh` action backs up the lexicon again and atomically
replaces **only cached source suggestions**, never saved pronunciations.
It may be repeated after updating the OpenRussian reference dump.

**Important:** the first `candidates-plan` may report
`schema_ready: false` until `init --confirm` has completed. Inspect
its sample and the candidate counts before applying.

Open the normal Ruslex URL, sign in, turn on **Edit & review mode**,
then open **Pronunciation review**. Test missing, source-backed, disputed,
deferred and meaning-ambiguous entries. Confirm that users without
edit permission cannot use the page's API.

This is not yet merged. Roll back code with:
`git switch main && ./manage.sh deploy`. Leave the optional
new tables in place; no data restore is required for a code rollback.
