# Ruslex day-to-day VPS operations, backup and recovery

All commands run from `/srv/apps/ruslex` over SSH unless otherwise stated.
Use [VPS_FOUNDATIONS.md](VPS_FOUNDATIONS.md) for the underlying server layout.

## Operations cheat sheet

```bash
./manage.sh status                # container status
./manage.sh health                # local web health endpoint
./manage.sh logs                  # web logs; Ctrl-C stops following logs
./manage.sh check                 # Django + legacy SQLite schema checks
./manage.sh backup                # consistent backups of BOTH databases
./manage.sh admin                 # create admin
./manage.sh stop                  # stop only Ruslex web container
./manage.sh start                 # restart only Ruslex web
./manage.sh disable               # stop web AND remove only its Caddy route
./manage.sh publish               # register its Caddy route again
./manage.sh remove-containers     # remove Ruslex containers; PRESERVE data
```

`./manage.sh deploy` is a deliberate release, **not** the normal restart
command. `./manage.sh update` remains as an alias for the old workflow but
should not be used in scripts with ambiguous meaning.

## Backups

`./manage.sh backup` uses SQLite's online backup API so an active WAL database
is captured consistently. It creates a new timestamped directory under
`/srv/data/ruslex/backups/` with:

- `lexicon.db`: lexemes, senses, tags, books, pages, reviews, occurrences.
- `admin.sqlite3`: Django users, groups, sessions, permissions and settings.

The two files are backed up separately, not as a single cross-database
transaction. This is acceptable for the current app, but record the backup
time, especially before changing admin permissions or restoring both DBs.

**Backups on the same VPS do not protect against VPS loss.** Also copy backups,
OCR originals, and the private `.env`/OpenCode credentials to a secure,
encrypted off-server destination. A scheduled backup can invoke
`cd /srv/apps/ruslex && ./manage.sh backup` as the deployment user; use your
existing VPS guide for systemd timers and off-site synchronization.

Test recovery periodically using disposable database copies, not the live
files. Do not `cp` a live SQLite database while the site is running.

## Safe restore (destructive; only if explicitly required)

First decide whether you need a code rollback (Git/image) or a data restore.
A code rollback **must not** overwrite the dictionary. To restore **both**
SQLite databases from one dated backup:

```bash
cd /srv/apps/ruslex
./manage.sh stop
./manage.sh restore \
  --from /srv/data/ruslex/backups/YYYYMMDD-HHMMSS-ffffff \
  --confirm
./manage.sh start
./manage.sh check
```

The restore script refuses to run while web is running, refuses incomplete
backup directories, checks SQLite integrity, and creates an additional
`before-manual-restore-*` backup before replacing DB files. It also stops if
SQLite `-wal` or `-shm` sidecars remain; inspect those instead of deleting
them blindly. Restoring the admin and lexicon DBs is done while web is
stopped, not atomically across two files.

For a **single** dictionary promotion rollback, do not automatically restore
the whole lexicon if users edited it since promotion. Review the changes and
restore only after confirming acceptable data loss.

## Book/AI processing commands

```bash
./process.sh build        # also prepares persistent OpenCode state permissions
./process.sh doctor       # verifies OpenCode can write its log/config folders
./process.sh version
./process.sh inventory
./process.sh audit        # Markdown + CSV review queues (read only)
./process.sh help
```

Processing is not a daemon and does not need a Caddy site. Run it only when
needed; do not overlap AI processing with a large web image build on a small
VPS. See [BOOK_PROCESSING.md](BOOK_PROCESSING.md) for the complete workflow.

## Diagnosing common failures

| Symptom | Check | Typical resolution |
| --- | --- | --- |
| Public 502 | `./manage.sh status`, `docker network inspect proxy` | Web container unhealthy or wrong Caddy upstream |
| Website works on 8790 but not HTTPS | Caddy snippet, `docker logs proxy-caddy-1` | DNS/TLS/Caddy route |
| Web fails at boot | `./manage.sh logs`, `./manage.sh check` | Missing data mount or permissions |
| Frontend build fails | `./manage.sh build`, npm lockfile, free memory | Fix Svelte errors, missing dependency, low RAM |
| Database locked | Active writer, pending SQLite transaction | Retry later, avoid simultaneous bulk promotion |
| OCR import detects changed page | Source differs from imported text | Correct source/edition; never overwrite silently |
| Promotion says live changed | A web user edited dictionary since workspace began | New workspace from fresh live snapshot |
| OpenCode `EACCES` under `/state` | `./process.sh doctor` | `./process.sh repair-state`, then retry `version` |
| OpenCode login/model fails | `./process.sh version`, `./process.sh auth`, model ID | Provider/CLI compatibility; test one small batch |
| Restore refuses `-wal` or `-shm` | SQLite sidecar left after stop | Diagnose journal state before manual intervention |

## Maintenance schedule

- After every app release: `health`, browser smoke check, backup reference.
- Before every bulk import or promotion: review `plan`, verify backup and disk.
- Weekly: check disk, Docker logs, backup timestamps, and processor workspace
  size. Example: `du -sh /srv/data/ruslex/processing/*`.
- Monthly: apply supported OS and container security updates using your server
  guide, rebuild at a tested revision, verify off-site backup restorability.
- When retiring an app: unpublish/stop, preserve data and code backups, then
  remove containers separately. Never run `docker network rm proxy` to remove
  Ruslex; the network belongs to multiple projects.

## Ownership boundaries

Only the deployment operator should run `manage.sh` and `process.sh`.
Django permissions grant users editor/reviewer access **inside the website**.
That is a different layer from Linux filesystem permissions, Docker CLI
privileges, and the model-provider account.
