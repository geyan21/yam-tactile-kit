import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.build import build
from tactile_kit.render import DOCS
from tactile_kit.packages import SELF_ARCHIVES


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.targets += [attrs[key] for key in ("href", "src") if attrs.get(key)]
        if "id" in attrs:
            self.ids.add(attrs["id"])


class ReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="yam-tactile-test-")
        cls.directory = Path(cls.temp.name)
        cls.output = cls.directory / "first"
        build(ROOT, cls.output, ROOT / "examples/design.example.json", ROOT / "examples/calibration.synthetic.csv")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_local_links_and_complete_guide(self):
        site = self.output / "site"
        parsers = {}
        for page in ("index.html", "guide.html"):
            parser = Links()
            parser.feed((site / page).read_text())
            parsers[page] = parser
        source_ids = {f"source-{ref['id']}" for ref in json.loads((ROOT / "web/references.json").read_text())}
        for name, parser in parsers.items():
            for link in parser.targets:
                parsed = urlsplit(link)
                if parsed.scheme or link.startswith("//"):
                    continue
                path = unquote(parsed.path)
                target = site / (path or name)
                with self.subTest(page=name, link=link):
                    self.assertTrue(target.is_file(), f"Missing local target {target}")
                    if parsed.fragment:
                        target_ids = parsers.get(path or name, parser).ids | source_ids
                        self.assertIn(parsed.fragment, target_ids)
        self.assertTrue({slug for _, slug, _ in DOCS}.issubset(parsers["guide.html"].ids))
        self.assertTrue({f"guide-{slug}" for _, slug, _ in DOCS}.issubset(parsers["index.html"].ids))
        self.assertIn("cad-view", parsers["index.html"].ids)
        self.assertIn("complete-download", parsers["index.html"].ids)
        ET.parse(self.output / "finger-concept.svg")

    def test_archive_integrity_and_scope(self):
        archive = self.output / "site/downloads/yam-tactile-kit.zip"
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            manifest = json.loads(bundle.read("yam-tactile-kit/SOURCE_MANIFEST.json"))
            self.assertIn("README.md", manifest["files"])
            self.assertIn(".github/workflows/pages.yml", manifest["files"])
            self.assertIn("scripts/export_git.py", manifest["files"])
            self.assertIn("reproduction/calibration.csv", manifest["files"])
            for name, expected in manifest["files"].items():
                self.assertEqual(hashlib.sha256(bundle.read(f"yam-tactile-kit/{name}")).hexdigest(), expected)
            self.assertTrue(all(name.startswith("yam-tactile-kit/") for name in names))
            self.assertFalse(any("/build/" in name or "/.git/" in name or "__pycache__" in name for name in names))

    def test_clean_extracted_checkout_reproduces_outputs(self):
        extracted = self.directory / "extracted"
        with zipfile.ZipFile(self.output / "site/downloads/yam-tactile-kit.zip") as bundle:
            bundle.extractall(extracted)
        checkout = extracted / "yam-tactile-kit"
        run = subprocess.run(
            [sys.executable, str(checkout / "scripts/reproduce.py")],
            cwd=checkout, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        for filename in (
            "design-summary.json", "calibration-report.json", "finger-concept.svg",
            "site/index.html", "site/guide.html", "site/assets/data.js",
            "site/downloads/yam-tactile-kit.zip", "yam-tactile-site.zip", "yam-tactile-complete.zip",
        ):
            with self.subTest(filename=filename):
                self.assertEqual((self.output / filename).read_bytes(), (checkout / "build" / filename).read_bytes())

    def test_prebuilt_website_archive_is_complete(self):
        with zipfile.ZipFile(self.output / "yam-tactile-site.zip") as bundle:
            for path in (self.output / "site").rglob("*"):
                if path.is_file() and path.relative_to(self.output / "site").as_posix() not in SELF_ARCHIVES:
                    self.assertEqual(
                        bundle.read("yam-tactile-site/" + path.relative_to(self.output / "site").as_posix()),
                        path.read_bytes(),
                    )

    def test_complete_handoff_contains_all_design_docs_source_and_website(self):
        with zipfile.ZipFile(self.output / "yam-tactile-complete.zip") as bundle:
            prefix = "yam-tactile-complete/"
            names = set(bundle.namelist())
            for name in (
                "README_FIRST.md", "source/README.md", "source/src/tactile_kit/geometry.py",
                "source/.github/workflows/pages.yml", "website/index.html", "website/assets/viewer.js",
                "documentation/guide.html", "documentation/markdown/HARDWARE.md",
                "design/assembly-envelopes.scad", "design/finger-envelope.stl",
                "design/bom.csv", "design/measurements.template.json",
            ):
                self.assertIn(prefix+name, names)
            manifest = json.loads(bundle.read(prefix+"HANDOFF_MANIFEST.json"))
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256(bundle.read(prefix+name)).hexdigest(), digest)
            self.assertFalse(manifest["hardware_validated"])
        with zipfile.ZipFile(self.output / "site/downloads/yam-tactile-docs.zip") as docs:
            guide = docs.read("yam-tactile-documentation/guide.html").decode()
            self.assertIn("<style>", guide)
            self.assertIn("data:image/svg+xml;base64,", guide)
            self.assertNotIn('src="assets/', guide)

    def test_repeated_build_does_not_nest_previous_release_archives(self):
        before = (self.output / "yam-tactile-complete.zip").read_bytes()
        build(ROOT, self.output, ROOT / "examples/design.example.json", ROOT / "examples/calibration.synthetic.csv")
        self.assertEqual(before, (self.output / "yam-tactile-complete.zip").read_bytes())

    def test_rebuild_removes_stale_pad_geometry(self):
        target = self.directory / "pad-removal"
        build(ROOT, target, ROOT / "examples/design.example.json", ROOT / "examples/calibration.synthetic.csv")
        design = json.loads((ROOT / "examples/design.example.json").read_text())
        design["face_width_mm"] = 3
        path = self.directory / "no-pad.json"
        path.write_text(json.dumps(design))
        build(ROOT, target, path, ROOT / "examples/calibration.synthetic.csv")
        self.assertFalse((target / "design/pad-envelope.stl").exists())
        self.assertFalse((target / "site/downloads/design/pad-envelope.stl").exists())
        with zipfile.ZipFile(target / "site/downloads/yam-tactile-designs.zip") as archive:
            self.assertFalse(any("pad-envelope.stl" in name for name in archive.namelist()))

    @unittest.skipUnless(shutil.which("git"), "Optional Git executable is not installed")
    def test_git_bundle_clones_to_a_checked_out_main_branch(self):
        git = str(Path(shutil.which("git")).resolve())
        bundle_path = self.directory / "verified.bundle"
        exported = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts/export_git.py"), "--git", git,
                "--archive", str(self.output / "site/downloads/yam-tactile-kit.zip"),
                "--output", str(bundle_path),
            ],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(exported.returncode, 0, exported.stderr)
        checkout = self.directory / "git-checkout"
        cloned = subprocess.run(
            [git, "clone", str(bundle_path), str(checkout)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(cloned.returncode, 0, cloned.stderr)
        self.assertTrue((checkout / "README.md").is_file(), "Clone did not check out files")
        branch = subprocess.run(
            [git, "-C", str(checkout), "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(branch.stdout.strip(), "main")
        status = subprocess.run(
            [git, "-C", str(checkout), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(status.stdout, "")

    def test_custom_inputs_are_carried_in_the_download(self):
        design = json.loads((ROOT / "examples/design.example.json").read_text())
        design.update({"face_width_mm": 10, "label": "Custom reproducibility check"})
        design_path = self.directory / "custom.json"
        design_path.write_text(json.dumps(design))
        custom = self.directory / "custom"
        build(ROOT, custom, design_path, ROOT / "examples/calibration.synthetic.csv")
        with zipfile.ZipFile(custom / "site/downloads/yam-tactile-kit.zip") as bundle:
            included = json.loads(bundle.read("yam-tactile-kit/reproduction/design.json"))
            self.assertEqual(included["face_width_mm"], 10)
        summary = json.loads((custom / "design-summary.json").read_text())
        self.assertEqual(summary["columns"], 4)


if __name__ == "__main__":
    unittest.main()
