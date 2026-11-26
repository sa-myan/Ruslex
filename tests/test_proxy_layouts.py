"""The Ruslex publisher must respect existing Caddy routes and host layouts."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import proxy


class PublisherLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _main(self, base: Path, inline: bool = False):
        (base / "sites").mkdir(parents=True)
        (base / "Caddyfile").write_text(
            "import /etc/caddy/sites/*.caddy\n" +
            (
                "ruslex.2-29-159-213.sslip.io {\n"
                "  reverse_proxy ruslex-web:8000\n"
                "}\n"
                if inline else ""
            )
        )

    def test_existing_flat_layout_and_inline_route_are_not_changed(self):
        self._main(self.root, inline=True)
        before = (self.root / "Caddyfile").read_bytes()
        with patch.object(proxy, "ROOT", self.root), patch.object(
            proxy, "hostname_from_env", return_value="ruslex.2-29-159-213.sslip.io"
        ), patch.object(proxy, "docker_caddy") as docker:
            for dry_run in (True, False):
                result = proxy.configure("publish", dry_run=dry_run)
                self.assertIn("already published inline", result)
            with self.assertRaisesRegex(RuntimeError, "refusing to unpublish"):
                proxy.configure("unpublish")
            docker.assert_not_called()
        self.assertEqual(before, (self.root / "Caddyfile").read_bytes())
        self.assertFalse((self.root / "sites" / "ruslex.caddy").exists())

    def test_legacy_config_layout_is_accepted(self):
        self._main(self.root / "config")
        with patch.object(proxy, "ROOT", self.root), patch.object(
            proxy, "hostname_from_env", return_value="ruslex.example.com"
        ):
            self.assertIn("reverse_proxy ruslex-web:8000", proxy.configure("publish", dry_run=True))
            self.assertFalse((self.root / "config" / "sites" / "ruslex.caddy").exists())

    def test_different_inline_upstream_refuses_to_modify(self):
        self._main(self.root, inline=True)
        main = self.root / "Caddyfile"
        main.write_text(main.read_text().replace("ruslex-web:8000", "old-web:8000"))
        with patch.object(proxy, "ROOT", self.root), patch.object(
            proxy, "hostname_from_env", return_value="ruslex.2-29-159-213.sslip.io"
        ):
            with self.assertRaisesRegex(RuntimeError, "different upstream"):
                proxy.configure("publish", dry_run=True)


if __name__ == "__main__":
    unittest.main()
