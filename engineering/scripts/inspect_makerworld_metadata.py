#!/usr/bin/python3
"""Summarize relevant original-model metadata without dumping unrelated fields."""

import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def safe_url(value):
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def sanitized(value):
    if isinstance(value, dict):
        return {key: sanitized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return safe_url(value)
    return value


def main():
    source = ROOT / "build/engineering/sources/makerworld_70d749bc.json"
    with execution(ROOT / "build/records", "Inspect original MakerWorld materials, geometry-file links, and license metadata") as record:
        data = json.loads(source.read_text())
        matches = []

        def walk(value, path=""):
            if isinstance(value, dict):
                for key, item in value.items():
                    child = f"{path}.{key}" if path else key
                    lowered = key.lower()
                    if any(word in lowered for word in ("license", "agreement", "fileurl", "filename", "modelfile", "filepath")):
                        preview = item
                        if isinstance(item, str):
                            preview = safe_url(item) if item.startswith("https://") else item
                        matches.append({"path": child, "value": str(preview)[:700]})
                    walk(item, child)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")
            elif isinstance(value, str) and value.startswith("https://"):
                extension = Path(urlsplit(value).path).suffix.lower()
                if extension in {".stl", ".stp", ".step", ".3mf", ".zip"}:
                    matches.append({"path": path, "asset_url": safe_url(value)})

        walk(data)
        profiles = []
        for instance in data.get("instances", []):
            if instance["id"] != 3349177:
                continue
            model = instance.get("extention", {}).get("modelInfo", {})
            profiles.append({
                "instance_id": instance["id"], "profile_id": instance.get("profileId"),
                "title": instance.get("title"), "updated": instance.get("updateTime"),
                "printer": model.get("compatibility"), "project_settings": model.get("projectSettings"),
                "plates": [{"index": p.get("index"), "filaments": p.get("filaments"), "weight_g": p.get("weight")} for p in model.get("plates", [])],
            })
        result = {
            "model_id": data["id"], "title": data["title"],
            "creator": data.get("designCreator", {}).get("name"),
            "top_level_keys": list(data), "profiles": profiles,
            "file_and_license_fields": matches,
            "design_extension": sanitized(data.get("designExtension")),
            "allow_recreation": data.get("allowReCreation"),
        }
        record["summary"] = result
        (source.parent / "makerworld_summary.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
