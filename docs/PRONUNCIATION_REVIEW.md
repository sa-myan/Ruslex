# Manual pronunciation review queue

The site now offers **Pronunciation review** when Edit mode is enabled. The
feature is for manually resolving unresolved stress, ё spelling and
meaning-specific homographs. It does **not** call an LLM, consult OpenRussian
from the web server, or change the existing ordinary lexeme review status.

The queue includes active ordinary words and abbreviations without any
pronunciation record. It has three views: Pending, Deferred, and All unresolved.
Each entry displays its stored English meanings and sample textbook context,
and reuses the existing stress/ё editor to save a reading and optionally
associate it with meanings. Successful saves leave the unresolved queue.
Deferrals are reversible and can include a private note (up to 1000 chars).
Skipping moves to the next entry; the queue wraps around.

**Limitations:** For this first UI, unresolved means *no pronunciation stored*.
Existing source-backed or disputed readings are not included even if they
could benefit from human verification. They can still be managed on the
individual entry's editor. The queue does not automatically select between
ambiguous OpenRussian candidates.

## Install on the existing single-user VPS without merging

This is a new optional schema in the existing lexicon SQLite database.
It must be explicitly initialized before using the new page.

```sh
cd /srv/apps/ruslex
git status --short  # must be clean
git fetch origin
git switch --detach origin/feat/pronunciation-review-queue
./process.sh build
./process.sh pronunciation-review plan
./manage.sh backup
./process.sh pronunciation-review init --confirm
./process.sh pronunciation-review plan
./manage.sh deploy
./manage.sh health
./manage.sh check
```

The `plan` command is read-only, `init` takes an extra consistent lexicon
backup before creating one table, and re-running it is harmless. This
modifies no existing pronunciation records, lexemes, senses or page evidence.
The usual `./manage.sh deploy` may briefly interrupt the public website.

Open the usual website, log in with edit permission, enable **Edit mode**, and
select **Pronunciation review** from the sidebar. Try deferring an entry,
reopening it from the Deferred queue, and saving a pronunciation.

A code-only rollback is `git switch main && ./manage.sh deploy`. The
optional new SQLite table is safe to leave in place, and no database restore
is necessary. Keep the feature unmerged until you've reviewed the interface.
