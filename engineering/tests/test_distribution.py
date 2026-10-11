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
        (site / "assets/data.js").write_text("window.ENGINEERING={};\n")
        (site / "assets/design-catalog.json").write_text(json.dumps({"source": "downloads/enpire-source.zip"}))
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
            catalog = json.loads((root / "hosted/assets/design-catalog.json").read_text())
            self.assertIn("/releases/download/kit-aaaaaaaaaaaa/enpire-source.zip", catalog["source"])
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

    def test_historical_cad_links_use_matching_immutable_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            relative = Path("f1/history/cad/retained.step")
            asset = site / "assets/development" / relative
            source = root / "source/engineering/development" / relative
            asset.parent.mkdir(parents=True); source.parent.mkdir(parents=True)
            asset.write_bytes(b"preserved historical CAD"); source.write_bytes(asset.read_bytes())
            page = asset.parent / "index.html"
            page.write_text('<a href="retained.step?download=1#part">STEP</a><a href="../../../../../index.html">Home</a>')
            manifest = prepare(site, root / "hosted", root / "packets", "e"*40, source_root=root / "source")
            output = (root / "hosted" / page.relative_to(site)).read_text()
            self.assertIn("/"+"e"*40+"/engineering/development/f1/history/cad/retained.step?download=1#part", output)
            self.assertFalse((root / "hosted" / asset.relative_to(site)).exists())
            self.assertEqual(asset.read_bytes(), b"preserved historical CAD")
            self.assertEqual(manifest["offloaded_repository_bytes"], len(asset.read_bytes()))

    def test_prototype_cad_copies_share_the_same_source_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); site = self.fixture(root)
            source = root / "source/engineering/prototypes/capacitive/cad/plate.step"
            source.parent.mkdir(parents=True); source.write_bytes(b"prototype plate")
            for prefix in ("assets", "downloads"):
                target = site / prefix / "prototypes/capacitive/cad/plate.step"
                target.parent.mkdir(parents=True); target.write_bytes(source.read_bytes())
            (site / "prototype.html").write_text(
                '<a href="assets/prototypes/capacitive/cad/plate.step">Module CAD</a>'
                '<a href="downloads/prototypes/capacitive/cad/plate.step">Table CAD</a>'
                '<a href="index.html">Home</a>')
            manifest = prepare(site, root / "hosted", root / "packets", "1"*40, source_root=root / "source")
            urls = {item["url"] for item in manifest["offloaded_repository_cad"].values()}
            self.assertEqual(len(urls), 1)
            self.assertEqual((root / "hosted/prototype.html").read_text().count(next(iter(urls))), 2)
            dynamic = (root / "hosted/assets/data.js").read_text()
            mapping = json.loads(dynamic.split("window.KIT_HOSTED_LINKS=", 1)[1].strip().removesuffix(";"))
            self.assertEqual(mapping["downloads/prototypes/capacitive/cad/plate.step"], next(iter(urls)))
            self.assertTrue((site / "downloads/prototypes/capacitive/cad/plate.step").is_file())

    def test_different_historical_source_is_not_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = self.fixture(root)
            asset = site / "assets/development/k1/part.stl"
            source = root / "source/engineering/development/k1/part.stl"
            asset.parent.mkdir(parents=True); source.parent.mkdir(parents=True)
            asset.write_bytes(b"site version"); source.write_bytes(b"different source")
            with self.assertRaisesRegex(ValueError, "immutable repository source"):
                prepare(site, root / "hosted", root / "packets", "f"*40, source_root=root / "source")


if __name__ == "__main__":
    unittest.main()
