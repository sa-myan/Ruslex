# Installation and ongoing deployment

**All steps can run on the VPS.** Start with [VPS_FOUNDATIONS.md](VPS_FOUNDATIONS.md),
which explains Ubuntu, Docker/Compose, one shared Caddy instance, the external
proxy network, DNS, `/srv` directories, persistent databases and first-install
commands from scratch.

- **First install:** `./manage.sh init --source-db /path/to/lexicon.db`, then
  `./manage.sh lock`, `./manage.sh build`, `./manage.sh deploy`, `./manage.sh publish`.
  If an existing database is already installed, omit `--source-db`.
- **Later releases:** `git pull --ff-only`, `./manage.sh build`,
  `./manage.sh test`, `./manage.sh deploy`. No Caddy modification.
- **Processing a new book:** see [BOOK_PROCESSING.md](BOOK_PROCESSING.md).
- **Backup and recovery:** see [OPERATIONS.md](OPERATIONS.md).

`deploy.sh` is a backwards-compatible alias for deployment, **not** a first
installation procedure. Never run first-install actions on an existing project
without verifying the state.
