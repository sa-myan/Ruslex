# Ruslex building and deployment (VPS only)

## Keep installation, release and Caddy separate

| Command | Changes | Does **not** do |
| --- | --- | --- |
| `./manage.sh init` | Initial folders/.env and optional initial dictionary import | Build/restart Caddy or overwrite live DB |
| `./manage.sh lock` | Generate frontend dependency lockfile via disposable Node container | Deploy |
| `./manage.sh build` | Compile image; checks Svelte first | Restart application |
| `./manage.sh deploy` | Preflight, build, backup, migrate admin DB, replace web, health check | Edit Caddy, process books, restore dictionary |
| `./manage.sh publish` | Create/validate/reload only `ruslex.caddy` | Build web |
| `./manage.sh unpublish` | Remove/validate/reload only Ruslex route | Delete data |
| `./manage.sh disable` | Stop Ruslex and unpublish its route | Remove DBs or affect other projects |
| `./manage.sh remove-containers` | Stop/remove Ruslex Compose containers | Remove shared `proxy` network, app checkout or data |

`deploy.sh` remains as a small alias for `./manage.sh deploy`; it is **no longer
an installer**. The old all-in-one `scripts/install.py` approach was split to
prevent accidental modifications to the global proxy during a code update.

## Routine release

```bash
cd /srv/apps/ruslex
git status --short
git pull --ff-only
# Commit changes before deploying; deploy refuses a dirty checkout by default.
./manage.sh doctor
./manage.sh build
./manage.sh test
./manage.sh deploy
./manage.sh status
./manage.sh health
```

### What happens inside `deploy`

1. Check `.env`, dictionary integrity, Compose config and `proxy` network.
2. Preserve the last web image under Docker tag `ruslex:previous` (if present).
3. Build and check the new frontend+backend image.
4. Make consistent online snapshots of **both** databases.
5. Run Django `check_lexicon`, `migrate --database=default`,
   `initialize_roles`, and `check` in short-lived containers.
6. Recreate **web only**, then check `127.0.0.1:8790/healthz`.
7. Record the code commit and image ID in the release log.

Django migrations affect the **admin** database only. The lexicon schema is
legacy and is not recreated by Django. The runtime entrypoint is deliberately
simple: it starts Gunicorn and **does not run migrations automatically**.

If web replacement fails, the release script attempts to restart the previous
image. That is **not** a guaranteed database rollback; consult the backup
records and examine any admin-schema migration before reverting.

### Check a patch or an uncommitted change

```bash
cd /srv/apps/ruslex
git status --short
./manage.sh build
./manage.sh test
# If satisfied, commit and then use ./manage.sh deploy.
```

`./manage.sh deploy --allow-dirty` exists for deliberate trials, but it is
not a recommended normal release. Don't let the deployment revision become
an unverifiable mixture of source and local patches.

### Reproducible frontend dependencies

The old Dockerfile used `npm install` without a lockfile. The new build uses
`npm ci` **when `frontend/package-lock.json` exists**; until then, it uses a
bootstrap install. Run `./manage.sh lock` once on the VPS, inspect/commit the
result and subsequent builds use `npm ci`. Lockfile generation needs network
access but no Node installation on the VPS host.

Python runtime dependencies are currently compatible-version ranges. For
strictly reproducible releases, generate and review a tested constraints file
and pin Docker base-image digests after the initial functional smoke checks.

## Deployment rollback

The website image is independent from the SQLite files. To roll back code:

1. Diagnose and record the failed release. Check `./manage.sh logs`.
2. Return Git to the last known good revision (e.g. `git switch` to a release tag
   or revert the offending commit), keeping uncommitted work safe.
3. `./manage.sh build` and `./manage.sh deploy` at that revision.
4. Restore data **only** if a deliberate schema or data change requires it;
   see [OPERATIONS.md](OPERATIONS.md).

The previous image is retained as `ruslex:previous` as an additional recovery
point, but a rebuild from a known Git revision is the primary method. Never
undo a web-code change by replacing the entire live lexicon DB.

## Caddy publication

Publish once or when the hostname changes:

```bash
cd /srv/apps/ruslex
./manage.sh publish --dry-run
./manage.sh publish
```

The script checks that `Caddyfile` imports `/etc/caddy/sites/*.caddy`, refuses
to modify an unmanaged file or duplicate hostname, validates the new config,
then **reloads** Caddy. It never runs `docker compose up` on `/srv/proxy`.

The site uses `PUBLIC_ORIGIN` from `.env`. If you change hostnames, update the
corresponding host and Django environment settings carefully, then republish.

## Processes and resource use

On a small 2 GB VPS, `npm ci` + Vite compilation and OpenCode model processing
can be temporarily heavy. Run `./process.sh` batch jobs sequentially and avoid
competing with deployments. There is no constantly running AI worker. Check:

```bash
docker stats --no-stream
df -h
free -h
./manage.sh status
```
