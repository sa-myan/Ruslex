# Preview a UI pull request without merging or interrupting production

**All commands here run on the VPS except the SSH tunnel command.** The
production checkout, database files, Caddy route and Docker Compose project
remain untouched. The preview listens on the VPS loopback interface only.

## Start a preview for PR #8

Create or refresh a dedicated worktree for the PR. If the directory already
exists, inspect it before replacing it; never run these commands inside the
production checkout.

```sh
cd /srv/apps/ruslex
git fetch origin
git worktree add --detach /srv/apps/ruslex-ui-preview origin/feat/readable-morphology-tables
```

If you already have a checkout at `/srv/apps/ruslex-ui-preview`, use
`git -C /srv/apps/ruslex-ui-preview fetch origin` and
`git -C /srv/apps/ruslex-ui-preview checkout --detach origin/feat/readable-morphology-tables`
instead; only do this when its working tree is clean.

Create an online-safe, consistent database backup using the **production** tool:

```sh
cd /srv/apps/ruslex
./manage.sh backup
```

Copy the *exact printed backup directory* (it contains `lexicon.db` and
`admin.sqlite3`), then start the preview image from the worktree:

```sh
cd /srv/apps/ruslex-ui-preview
sh scripts/preview_ui.sh start /srv/data/ruslex/backups/PASTE_EXACT_BACKUP_DIRECTORY_NAME
sh scripts/preview_ui.sh status
curl -fsS http://127.0.0.1:8791/healthz
```

The launcher builds `ruslex-ui-preview:local` and runs
`ruslex-ui-preview` with its **own editable copies** of the two databases.
The preview uses its own Docker bridge network, not the shared `proxy` network.
It is bound only to `127.0.0.1:8791`; do not publish that port publicly.

To view the interface from a laptop or from Android Termux, open a **separate
terminal on your device**, substituting your working SSH host alias:

```sh
ssh -N -L 8791:127.0.0.1:8791 myvps
```

Open `http://127.0.0.1:8791` on that **same device**. Keep the SSH
session open while browsing. No public DNS or Caddy change is needed.
With the preview's `HTTPS_ENABLED=0`, auth cookies can work over the local
HTTP tunnel, but any edits affect **only the disposable database copy**.

Suggested visual checks: noun declension, adjective declension and short
forms, verb present/future/past/imperative, lexicalized inflecting abbreviation
(`вуз`), indeclinable initialism (`МГУ`), very long raw paradigms, and
mobile layout. Verify the original Ruslex URL still loads simultaneously.

## Stop the preview

```sh
cd /srv/apps/ruslex-ui-preview
sh scripts/preview_ui.sh stop
```

The launcher deliberately retains the private snapshot directory it printed.
Once you no longer need that copy, delete **only that exact displayed
`/srv/data/ruslex/ui-preview-...` directory** yourself. Never remove
`/srv/data/ruslex/lexicon`, `/srv/data/ruslex/admin`, or the backups tree.

The preview requires no `manage.sh deploy`, no migration, no
`docker compose up`, and no modification of `/srv/proxy`.
