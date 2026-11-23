# VPS foundations: how Ruslex fits the server

**Everything in this guide can be done over SSH on your VPS.** A Windows PC,
Android tablet, local Node installation or local Python interpreter is **not**
required. The only files you must transfer are your book OCR exports (or download
them directly onto the VPS) and your application code (normally via Git).

For full Ubuntu SSH, Docker installation, firewall, backups, server replacement,
and general project-management instructions, read [VPS_WORKFLOW.md](VPS_WORKFLOW.md).
This document is the **Ruslex-specific map** of that shared infrastructure.

## Mental model: four different layers

```
INTERNET                              VPS: 80/443 (only Caddy)
   |                                       |
   +-- https://ruslex.example.com --------v
                                    shared Caddy container
                                    /srv/proxy
                                         |
                              external Docker network: proxy
                                         |
                      ruslex-web:8000 (Django/Gunicorn)
                        /srv/apps/ruslex; Compose name ruslex
                                         |
                             /srv/data/ruslex (bind mount)
                                   |              |
                            lexicon/lexicon.db  admin/admin.sqlite3

                     Separate, on-demand Compose project: ruslex-processing
                       OCR files  ->  workspace candidate  ->  manual promotion
                         /ocr           /processing              /lexicon
                                 (NO open port, NO Caddy route)
```

**Host** = Ubuntu running Docker. **Image** = immutable build result containing
application code and dependencies. **Container** = running instance of an
image. **Volume/bind mount** = durable host files mounted into a container.
**Network** = container-to-container addressing. **Reverse proxy** = Caddy,
which accepts TLS and sends a request to the correct service by hostname.

Git does not contain live databases, credentials, model authorization or OCR
workspaces. A container rebuild does not touch those data directories.

## Directory ownership and persistence

| Host path | Purpose | Lifetime |
| --- | --- | --- |
| `/srv/proxy` | The one shared Caddy proxy and site snippets | All projects |
| `/srv/apps/ruslex` | Git code, Dockerfiles, Compose files and scripts | Can be recreated from Git |
| `/srv/data/ruslex/lexicon/lexicon.db` | **Live language dictionary**, including reviewed senses | Precious; backup |
| `/srv/data/ruslex/admin/admin.sqlite3` | Django users, passwords, permissions and sessions | Precious; backup |
| `/srv/data/ruslex/ocr` | Original OCR JSON, ZIP or Markdown sources | Preserve originals |
| `/srv/data/ruslex/processing/<workspace>` | Candidate DB, AI stages, decisions, reports | Review / archive |
| `/srv/data/ruslex/processing/state` | Private OpenCode login, cache and credentials | Mode 0700/0750; don't commit |
| `/srv/data/ruslex/backups` | SQLite snapshots created before releases and promotions | Local only; copy off VPS |
| `/srv/data/ruslex/releases` | Release log with Git revision and image ID | Operational history |

**Why `/srv`?** It is a good convention for service data, not a requirement of
Docker. What matters is separation of application source from persistent data.

The Docker bind mount `${DATA_ROOT}:/data` exposes the same existing host DBs to
the website without copying DBs into the image. `DATA_ROOT` in `.env` determines
where the host directories live; `DATA_DIR=/data` is the *container* path.

## One-time prerequisites on a fresh Ubuntu VPS

Use the detailed commands and safety instructions in `docs/VPS_WORKFLOW.md`:

1. Configure SSH public-key login and an ordinary administrator account.
2. Enable the firewall with SSH and ports **80/443**; install Docker Engine and
   the **Compose plugin** (not the obsolete `docker-compose` binary).
3. Create `/srv/apps`, `/srv/data`, `/srv/proxy`, `/srv/admin`; create the shared
   Docker network **once** with `docker network create proxy`.
4. Bring up one Caddy Compose project under `/srv/proxy`. Its Caddyfile must
   import `/etc/caddy/sites/*.caddy` from host `/srv/proxy/config/sites`.
5. Configure your hostname's DNS to reach the VPS. A `sslip.io` hostname is
   convenient for testing but can change if the VPS IP changes.
6. Give the deployment user permission to use Docker (understand that this
   effectively grants root-level privileges), and ensure it owns only its
   application and data directories, not all of `/srv`.
7. Consider swap on a 2 GB server so frontend *builds* can complete. A memory
   warning during builds is separate from website runtime memory usage.

For an **existing configured VPS**, do not recreate Docker, the network,
Caddy, or users. Check them instead:

```bash
docker version
docker compose version
docker network inspect proxy
docker ps --format 'table {{.Names}}\t{{.Ports}}'
ls -la /srv/proxy/config/sites
```

## Why only Caddy owns port 443

A single VPS cannot run several independent containers all binding host
port 443. Caddy alone publishes 80/443. It reads the incoming **hostname**
and sends requests to the correct container using Docker DNS:

```
ruslex.example.com {
    encode zstd gzip
    reverse_proxy ruslex-web:8000
}
```

`ruslex-web` is a deliberately unique network alias belonging to Ruslex.
Caddy's `localhost` is Caddy itself, *not* the host or the Ruslex container.
The optional `127.0.0.1:8790:8000` mapping exists only for diagnosis from
inside the VPS; it is not a public listening port.

`docker-compose.yml` connects **only web** to the external `proxy` network.
The processing Compose project uses a private network and publishes no ports;
its `promoter` service has **no network connection at all**. Nothing in its
configuration can register it as a website.

## First Ruslex installation (VPS)

```bash
sudo mkdir -p /srv/apps /srv/data
# Clone code, or unpack the downloaded project bundle.
git clone https://github.com/sa-myan/Ruslex.git /srv/apps/ruslex
cd /srv/apps/ruslex

# Existing installation: preserves both DBs and .env.
./manage.sh init --dry-run
./manage.sh init

# First installation when no live lexicon exists:
# ./manage.sh init --source-db /path/to/your/verified/lexicon.db

./manage.sh doctor
./manage.sh lock        # Generate frontend/package-lock.json ON THE VPS; commit it.
./manage.sh build
./manage.sh deploy      # Commit code first, or add --allow-dirty for a controlled trial.
./manage.sh publish     # Only now register the Ruslex hostname in shared Caddy.
./manage.sh admin
```

On a first installation, `init` creates environment secrets, checks DB integrity,
and creates directories, **not** Caddy routes or application containers.
Subsequent calls never overwrite your database or `.env`. If you use a
non-default directory, provide `--data-root /some/path` **on the first call**.

Don't run the first-install commands blindly on an already running system; use
[DEPLOYMENT.md](DEPLOYMENT.md) for ordinary releases.

## What actually runs in the web container

1. Docker builds a Node stage to compile Svelte/Vite assets.
2. Docker builds a Python stage with Django, Gunicorn and WhiteNoise.
3. Compiled frontend assets are copied into the Python runtime image.
4. Gunicorn serves both the Django API and Svelte static assets on **8000**.
5. Caddy proxies HTTPS requests to that container, without rebuilding itself.

**No Vite server or Node process is needed in production.** Node is only in
the temporary build stage and the separate optional processing image.

## Limits and responsibilities

The VPS needs internet access to download container images, npm/pip packages,
and contact AI providers. Local filesystem changes to your dictionary always
remain on the VPS. AI processing is manual, on-demand, and not a website
request. Off-server backups are essential even though day-to-day work runs
entirely on the VPS.

Next: [DEPLOYMENT.md](DEPLOYMENT.md), [BOOK_PROCESSING.md](BOOK_PROCESSING.md),
[OPERATIONS.md](OPERATIONS.md).
