#!/usr/bin/env python3
"""Fresh installation only. Never reads or edits any previous v4 checkout.

  python3 scripts/install.py --dry-run
  python3 scripts/install.py
  python3 scripts/install.py --hostname my-host.example --no-publish

The first installation copies data/lexicon.db using SQLite backup() and creates
an entirely separate administrative database. Later runs preserve both.
"""
from __future__ import annotations
import argparse
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "ruslex.2-29-159-213.sslip.io"
CADDY_MAIN = Path("/srv/proxy/config/Caddyfile")
CADDY_SITE = Path("/srv/proxy/config/sites/ruslex.caddy")


def call(*args, **opts):
    print("+", *args, flush=True)
    return subprocess.run(args, check=True, cwd=ROOT, **opts)


def prepare_data(root: Path, *, dry_run=False):
    lexicon = root / "lexicon" / "lexicon.db"
    admin = root / "admin" / "admin.sqlite3"
    original = ROOT / "data" / "lexicon.db"
    if not original.is_file():
        raise RuntimeError(f"Bundled lexicon snapshot missing: {original}")
    for file in (original, lexicon) if lexicon.exists() else (original,):
        with sqlite3.connect(f"file:{file.resolve()}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {file}")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError(f"Foreign key errors in {file}")
    print(f"Lexicon target: {lexicon} ({'preserving existing' if lexicon.exists() else 'first-time SQLite copy'})")
    print(f"Admin target: {admin} ({'preserving existing' if admin.exists() else 'new Django-owned database'})")
    if dry_run:
        return
    for folder in (root, root/"lexicon", root/"admin", root/"backups"):
        folder.mkdir(parents=True,exist_ok=True)
        folder.chmod(0o750)
    if not lexicon.exists():
        with sqlite3.connect(f"file:{original.resolve()}?mode=ro",uri=True) as source:
            with sqlite3.connect(lexicon) as dest:
                source.backup(dest)
        lexicon.chmod(0o640)
    if lexicon.resolve() == admin.resolve():
        raise RuntimeError("Refusing to share the dictionary and admin database")


def write_env(hostname: str, data_root: Path, dry_run=False):
    env = ROOT / ".env"
    if env.exists():
        print(f"Keeping existing settings: {env}")
        if not dry_run:
            contents=env.read_text()
            configured=[line.split('=',1)[1].strip() for line in contents.splitlines() if line.startswith('PUBLIC_ORIGIN=')]
            if configured and configured[0] != 'https://' + hostname:
                print(f"Warning: existing hostname {configured[0]} differs from requested {hostname}; not overwriting .env")
        return
    print(f"Creating new private .env for {hostname}")
    if dry_run:return
    text = (f"DJANGO_SECRET_KEY={secrets.token_urlsafe(48)}\n"
            f"DJANGO_ALLOWED_HOSTS={hostname},127.0.0.1,localhost\n"
            f"PUBLIC_ORIGIN=https://{hostname}\n"
            f"HTTPS_ENABLED=1\n"
            f"DATA_ROOT={data_root}\n"
            f"PUID={os.getuid()}\nPGID={os.getgid()}\n")
    env.write_text(text)
    env.chmod(0o600)


def check_local_health():
    endpoint = "http://127.0.0.1:8790/healthz"
    for _ in range(60):
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as response:
                if response.status==200 and response.read().strip()==b"ok":
                    print("Local Django and database health checks PASSED")
                    return
        except (OSError,urllib.error.URLError):
            pass
        time.sleep(2)
    call("docker","compose","ps","-a")
    call("docker","compose","logs","--tail=100","web")
    raise RuntimeError(f"Application is not healthy at {endpoint}")


def publish(host: str, *, dry_run=False):
    site_text = ("# Managed by the standalone Ruslex installer\n"
                 f"{host} {{\n"
                 "    encode zstd gzip\n"
                 "    reverse_proxy ruslex-web:8000\n"
                 "}\n")
    if not CADDY_MAIN.is_file() or not CADDY_SITE.parent.is_dir():
        print("Caddy installation does not match the VPS guide; configuration not changed.")
        print("Add this block to the actual Caddy installation:\n"+site_text)
        return
    if "import /etc/caddy/sites/*.caddy" not in CADDY_MAIN.read_text():
        print("Caddyfile has no expected /etc/caddy/sites/*.caddy import; not modifying proxy.")
        print(site_text)
        return
    for path in CADDY_SITE.parent.glob("*.caddy"):
        if path != CADDY_SITE and re.search(r"(?<![A-Za-z0-9])"+re.escape(host)+r"(?![A-Za-z0-9])",path.read_text()):
            raise RuntimeError(f"Hostname already appears in unrelated Caddy site: {path}")
    previous=CADDY_SITE.read_text() if CADDY_SITE.exists() else None
    if previous is not None and previous != site_text and not previous.startswith("# Managed by the standalone Ruslex installer"):
        raise RuntimeError(f"Refusing to overwrite unmanaged Caddy site: {CADDY_SITE}")
    print("Caddy route:", CADDY_SITE)
    if dry_run:return
    # The entire config directory is mounted read-only in the container,
    # but the host-side file is writable to the deployment account.
    if previous != site_text:CADDY_SITE.write_text(site_text)
    try:
        call("docker","exec","proxy-caddy-1","caddy","validate","--config","/etc/caddy/Caddyfile")
        call("docker","exec","proxy-caddy-1","caddy","reload","--config","/etc/caddy/Caddyfile")
    except Exception:
        if previous is None:CADDY_SITE.unlink(missing_ok=True)
        else:CADDY_SITE.write_text(previous)
        try:call("docker","exec","proxy-caddy-1","caddy","reload","--config","/etc/caddy/Caddyfile")
        except Exception:pass
        raise
    print(f"Caddy routing reloaded. Public address: https://{host}")
    print("TLS certificate provisioning may complete after Caddy reload; check its logs if HTTPS fails.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hostname",default=DEFAULT_HOST)
    p.add_argument("--data-root",default="/srv/data/ruslex",type=Path)
    p.add_argument("--no-publish",action="store_true")
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?",args.hostname) or '.' not in args.hostname:
        p.error("Hostname must be a valid FQDN")
    data_root=args.data_root.resolve()
    if data_root.is_relative_to(ROOT):p.error("Databases must be outside the application checkout")
    if args.dry_run:
        print("DRY RUN — nothing will be created or changed")
        prepare_data(data_root,dry_run=True)
        write_env(args.hostname,data_root,dry_run=True)
        if not args.no_publish:publish(args.hostname,dry_run=True)
        return
    for prog in ("docker",):
        if not shutil.which(prog):raise RuntimeError("Docker is not installed")
    call("docker","compose","version")
    call("docker","info","--format","{{.ServerVersion}}")
    call("docker","network","inspect","proxy",stdout=subprocess.DEVNULL)
    prepare_data(data_root)
    write_env(args.hostname,data_root)
    call("docker","compose","config","--quiet")
    call("docker","compose","build","web")
    call("docker","compose","up","-d","--force-recreate","web")
    check_local_health()
    if not args.no_publish:
        publish(args.hostname)
    print("Installation completed. Create your administrator: ./manage.sh admin")

if __name__=="__main__":
    import shutil
    try:main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        sys.exit(f"ERROR: {exc}")
