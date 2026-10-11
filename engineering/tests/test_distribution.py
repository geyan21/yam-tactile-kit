"""Hosted downloads must retain their verified offline counterparts."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engineering/scripts"))
from prepare_pages_distribution import ARCHIVES, prepare, digest
from publish_download_distribution import verify_local


class DistributionTests(unittest.TestCase):
    def fixture(self, root):
        site = root / "offline"
        (site / "downloads").mkdir(parents=True)
        (site / "assets").mkdir()
        (site / "assets/cad.step").write_bytes(b"independent CAD payload")
        (site / "assets/file-index.html").write_text(
            '<a href="../downloads/enpire-source.zip">Full source</a><a href="../index.html">Home</a>')
        (site / "index.html").write_text(
            '<a href="downloads/enpire-source.zip">Source</a>'
            '<a href="downloads/yam-tactile-complete.zip">Complete</a>'
            '<a href="assets/cad.step">CAD</a>')
        for name in ARCHIVES:
            (site / "downloads" / name).write_bytes(("checked packet "+name).encode())
        (site / "downloads/yam-tactile-complete.zip").write_bytes(b"legacy offline alias")
        return site

    def test_hosted_links_change_without_mutating_offline_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            original = {p.relative_to(site): digest(p) for p in site.rglob("*") if p.is_file()}
            manifest = prepare(site, root / "hosted", root / "packets", "a"*40)
            self.assertEqual(original, {p.relative_to(site): digest(p) for p in site.rglob("*") if p.is_file()})
            page = (root / "hosted/index.html").read_text()
            self.assertIn("/releases/download/kit-aaaaaaaaaaaa/enpire-source.zip", page)
            self.assertIn("/releases/download/kit-aaaaaaaaaaaa/enpire-engineering-kit.zip", page)
            self.assertIn('href="assets/cad.step"', page)
            nested = (root / "hosted/assets/file-index.html").read_text()
            self.assertIn("/releases/download/kit-aaaaaaaaaaaa/enpire-source.zip", nested)
            self.assertNotIn("../https:", nested)
            self.assertFalse((root / "hosted/downloads/enpire-source.zip").exists())
            self.assertEqual((root / "hosted/assets/cad.step").read_bytes(), b"independent CAD payload")
            verify_local(root / "packets", manifest)

    def test_changed_packet_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            manifest = prepare(site, root / "hosted", root / "packets", "b"*40)
            (root / "packets/enpire-source.zip").write_bytes(b"changed payload")
            with self.assertRaisesRegex(ValueError, "asset changed"):
                verify_local(root / "packets", manifest)

    def test_staging_size_and_existing_output_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "staging bound"):
                prepare(site, root / "hosted", root / "packets", "c"*40, maximum_bytes=1)
            (root / "hosted/keep.txt").write_text("preserved")
            with self.assertRaisesRegex(ValueError, "Preserve staged outputs"):
                prepare(site, root / "hosted", root / "packets", "c"*40)
            self.assertEqual((root / "hosted/keep.txt").read_text(), "preserved")

    def test_asset_path_cannot_leave_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            manifest = prepare(site, root / "hosted", root / "packets", "d"*40)
            manifest["assets"]["../unexpected"] = {"bytes": 0, "sha256": "0"*64}
            with self.assertRaisesRegex(ValueError, "plain public filenames"):
                verify_local(root / "packets", manifest)


if __name__ == "__main__":
    unittest.main()
