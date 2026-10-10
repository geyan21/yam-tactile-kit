from collections import Counter
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.geometry import cross, scene, stl


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.design = json.loads((ROOT / "examples/design.example.json").read_text())

    def test_component_meshes_are_closed_oriented_and_have_expected_volume(self):
        model = scene(self.design)
        self.assertFalse(model["hardware_validated"])
        self.assertEqual(model["kind"], "concept_envelopes")
        for part in model["components"]:
            with self.subTest(part=part["id"]):
                undirected = Counter()
                directed = Counter()
                volume = 0
                for face in part["faces"]:
                    for a, b in zip(face, face[1:]+face[:1]):
                        undirected[tuple(sorted((a, b)))] += 1
                        directed[(a, b)] += 1
                    a, b, c = [part["vertices"][i] for i in face]
                    volume += sum(x*y for x, y in zip(a, cross(b, c)))/6
                self.assertTrue(all(count == 2 for count in undirected.values()))
                self.assertTrue(all(directed[(b, a)] == count for (a, b), count in directed.items()))
                self.assertGreater(volume, 0)
                self.assertEqual(stl(part).count("facet normal"), 12)
                if part["id"] == "finger":
                    self.assertAlmostEqual(volume, (5+0.8)/2*6*60)
                else:
                    sizes = [
                        max(v[i] for v in part["vertices"])-min(v[i] for v in part["vertices"])
                        for i in range(3)
                    ]
                    self.assertAlmostEqual(volume, sizes[0]*sizes[1]*sizes[2])

    def test_pad_is_omitted_when_no_cells_fit_or_stack_is_zero(self):
        for change in ({"face_width_mm": 3}, {"pad_stack_mm": 0}):
            model = scene({**self.design, **change})
            self.assertNotIn("pad", {part["id"] for part in model["components"]})

    def test_measured_inputs_do_not_promote_placeholder_geometry_to_validated_hardware(self):
        model = scene({**self.design, "geometry_status": "measured_inputs"})
        self.assertFalse(model["hardware_validated"])
        self.assertIn("Illustrative", model["assumptions"]["status"])
        self.assertTrue(all(part["envelope_only"] for part in model["components"]))
