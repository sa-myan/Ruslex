# Clean installation / deployment

This is the **first-install** process for a standalone app. It does not stop, replace, import, archive or delete any old v4 installation.

## Prerequisites

- An Ubuntu VPS with Docker Engine and Docker Compose plugin.
- Existing external Docker network named `proxy` and Caddy container `proxy-caddy-1`, as described in `VPS_WORKFLOW.md`.
- Write access to `/srv/apps/ruslex`, `/srv/data/ruslex`, and (if automatic HTTPS publishing is desired) `/srv/proxy/config/sites/`.
- Inbound 80/443 open on the VPS; Caddy maintains the TLS certificates.

Do not execute the installer as root unless your normal deployment workflow requires that; it records your current UID and GID for the container. The database directory must be writable by that same host user.

## Installation

Copy the complete archive to the VPS. As the `deploy` account, extract with the top-level `ruslex/` directory intact into `/srv/apps`. Then:

```bash
cd /srv/apps/ruslex
./deploy.sh --dry-run
./deploy.sh
./manage.sh admin
./manage.sh test
```

The first run creates `/srv/data/ruslex/{lexicon,admin,backups}`, makes a consistent copy of the bundled dictionary, creates `.env` with a generated random secret, validates Compose, builds the image (including the frontend and a non-root Django import test), starts Gunicorn, runs **admin-only migrations** and role initialization, and checks `http://127.0.0.1:8790/healthz`. If its expected Caddy configuration exists, it adds **only** `/srv/proxy/config/sites/ruslex.caddy`, validates and reloads Caddy.

It never overwrites a database on a subsequent run. It never removes an old service. This hostname is distinct from old v4: `ruslex.2-29-159-213.sslip.io`.

If the guide's Caddy layout is not present, the installer prints the new site block and leaves the running proxy configuration unchanged. Inspect `docker inspect proxy-caddy-1` to locate the real Caddy mount before publishing manually.

## Diagnostic commands

```bash
cd /srv/apps/ruslex
./manage.sh status
./manage.sh logs
curl -i http://127.0.0.1:8790/healthz
curl -i https://ruslex.2-29-159-213.sslip.io/healthz
./manage.sh check
./manage.sh test
```

A healthy endpoint confirms that both SQLite connections are reachable, not that every editing workflow has been tested. Check that the compiled Svelte page and static assets load in a browser, then sign in and test edits on the **fresh installation**.

## Rollback / maintenance

The old services are unrelated. Stop the fresh installation with `./manage.sh stop`; its data remains under `/srv/data/ruslex`. Back up with `./manage.sh backup` before every application upgrade. To remove only this project's public route, delete `/srv/proxy/config/sites/ruslex.caddy` **after checking it is the managed Ruslex file**, validate and reload Caddy. Never run `docker compose down -v` without understanding what it removes.

If you need another hostname, use:

```bash
python3 scripts/install.py --hostname another.example.org --no-publish
```

**Note**: existing `.env` is deliberately preserved; to change a previously configured hostname, update `DJANGO_ALLOWED_HOSTS` and `PUBLIC_ORIGIN` in `.env`, then restart the container and manage the Caddy site appropriately. The installer warns rather than silently overwrites settings.
