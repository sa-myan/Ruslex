"""Check that favicon references resolve inside Vite's /static/ build base."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
PUBLIC = PROJECT / "frontend" / "public"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "link":
            self.links.append(dict(attrs))


class FaviconAssetTest(unittest.TestCase):
    def test_links_reference_copied_static_assets(self):
        parser = LinkParser()
        parser.feed((PROJECT / "frontend" / "index.html").read_text())
        icons = [link for link in parser.links if "icon" in link.get("rel", "")]
        self.assertGreaterEqual(len(icons), 4)
        for link in icons:
            self.assertTrue(link["href"].startswith("/static/"))
            self.assertTrue((PUBLIC / link["href"].removeprefix("/static/")).is_file())

    def test_svg_png_ico_and_manifest_are_valid(self):
        ET.parse(PUBLIC / "favicon.svg")
        for name in ("favicon-16.png", "favicon-32.png", "icon-192.png", "icon-512.png"):
            self.assertTrue((PUBLIC / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue((PUBLIC / "favicon.ico").read_bytes().startswith(b"\x00\x00\x01\x00"))
        manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text())
        for icon in manifest["icons"]:
            self.assertTrue(icon["src"].startswith("/static/"))
            self.assertTrue((PUBLIC / icon["src"].removeprefix("/static/")).is_file())


if __name__ == "__main__":
    unittest.main()
