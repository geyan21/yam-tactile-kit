"""Small renderer for the controlled Markdown subset used by this repository."""

from __future__ import annotations

import html
from pathlib import Path
import re


DOCS = [
    ("REPLICATE.md", "replicate", "Reproduce the kit"),
    ("DESIGN_FILES.md", "design-files", "Get and edit the design files"),
    ("HARDWARE.md", "hardware", "Develop the hardware"),
    ("CALIBRATION.md", "calibration", "Calibrate recorded data"),
    ("VALIDATION.md", "validation", "Validate a physical build"),
    ("DESIGN_REVIEW.md", "review", "Read the original review"),
    ("SCOPE.md", "scope", "Scope and provenance"),
    ("YAM_CONTEXT.md", "yam-context", "YAM integration context"),
]


def _target(target: str) -> str:
    basename = target.split("/")[-1]
    for filename, slug, _ in DOCS:
        if basename == filename:
            return f"guide.html#{slug}"
    if basename == "yam_force_finger_concept.svg":
        return "assets/original-concept.svg"
    return target


def inline(text: str) -> str:
    token = re.compile(r"(`[^`]+`|!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)|\*\*.+?\*\*)")
    result = []
    for fragment in token.split(text):
        if fragment.startswith("`") and fragment.endswith("`"):
            result.append(f"<code>{html.escape(fragment[1:-1])}</code>")
        elif fragment.startswith("**") and fragment.endswith("**"):
            result.append(f"<strong>{html.escape(fragment[2:-2])}</strong>")
        elif re.match(r"!?\[", fragment):
            match = re.fullmatch(r"(!?)\[([^\]]*)\]\(([^)]+)\)", fragment)
            if not match:
                result.append(html.escape(fragment))
                continue
            image, label, target = match.groups()
            target = html.escape(_target(target), quote=True)
            if image:
                result.append(f'<img class="doc-image" src="{target}" alt="{html.escape(label, quote=True)}">')
            else:
                external = ' target="_blank" rel="noopener noreferrer"' if target.startswith("https://") else ""
                result.append(f'<a href="{target}"{external}>{html.escape(label)}</a>')
        else:
            result.append(html.escape(fragment))
    return "".join(result)


def markdown(text: str) -> str:
    lines = text.splitlines()
    blocks, paragraph, listing = [], [], None
    cursor = 0

    def flush():
        nonlocal listing
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if listing:
            blocks.append(f"</{listing}>")
            listing = None

    while cursor < len(lines):
        line = lines[cursor]
        if line.startswith("```"):
            flush()
            code = []
            cursor += 1
            while cursor < len(lines) and not lines[cursor].startswith("```"):
                code.append(lines[cursor])
                cursor += 1
            blocks.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
        elif line.startswith("|") and cursor + 1 < len(lines) and re.match(r"\|[\s:|-]+\|", lines[cursor + 1]):
            flush()
            cells = lambda row: [inline(cell.strip()) for cell in row.strip().strip("|").split("|")]
            blocks.append('<div class="table-scroll"><table><thead><tr>')
            blocks.extend(f"<th>{cell}</th>" for cell in cells(line))
            blocks.append("</tr></thead><tbody>")
            cursor += 2
            while cursor < len(lines) and lines[cursor].startswith("|"):
                blocks.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells(lines[cursor])) + "</tr>")
                cursor += 1
            blocks.append("</tbody></table></div>")
            continue
        elif match := re.match(r"^(#{1,6})\s+(.+)$", line):
            flush()
            level = min(5, len(match.group(1)) + 1)
            blocks.append(f"<h{level}>{inline(match.group(2))}</h{level}>")
        elif match := re.match(r"^(?:([-*])|\d+\.)\s+(.+)$", line):
            if paragraph:
                blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
                paragraph.clear()
            kind = "ul" if match.group(1) else "ol"
            if listing != kind:
                if listing:
                    blocks.append(f"</{listing}>")
                listing = kind
                blocks.append(f"<{kind}>")
            blocks.append(f"<li>{inline(match.group(2))}</li>")
        elif not line.strip():
            flush()
        else:
            if listing:
                blocks.append(f"</{listing}>")
                listing = None
            paragraph.append(line.strip())
        cursor += 1
    flush()
    return "\n".join(blocks)


def guide_content(root: Path) -> tuple[str, str]:
    sections, nav = [], []
    for filename, slug, title in DOCS:
        nav.append(f'<a href="#{slug}">{html.escape(title)}</a>')
        content = markdown((root / "docs" / filename).read_text(encoding="utf-8"))
        sections.append(f'<section id="{slug}" class="guide-section">{content}</section>')
    return "\n".join(sections), "\n".join(nav)


def embedded_guides(root: Path) -> str:
    sections = []
    for number, (filename, slug, title) in enumerate(DOCS, 1):
        content = markdown((root / "docs" / filename).read_text(encoding="utf-8"))
        content = content.replace('href="guide.html#', 'href="#guide-')
        sections.append(
            f'<details class="embedded-guide" id="guide-{slug}">'
            f'<summary><span class="chapter-number">{number:02d}</span>'
            f'<span>{html.escape(title)}</span><span class="chapter-open">Read +</span></summary>'
            f'<article class="guide-section">{content}</article></details>'
        )
    return "\n".join(sections)


def concept_svg(d: dict, result: dict) -> str:
    width = d["face_width_mm"]
    length = d["finger_length_mm"]
    label = html.escape(d["label"])
    cols, rows = result["columns"], result["rows"]
    grid = []
    if 0 < cols * rows <= 1024:
        for row in range(rows):
            for col in range(cols):
                grid.append(
                    f'<rect x="{718 + col * 110 / cols:.2f}" y="{207 + row * 154 / rows:.2f}" '
                    f'width="{max(0.1, 110 / cols - 1):.2f}" height="{max(0.1, 154 / rows - 1):.2f}" rx="1" fill="#cd9760"/>'
                )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="470" viewBox="0 0 1120 470">
<style>text{{font-family:Arial,sans-serif;fill:#183b42}}.small{{font-size:15px}}.label{{font-size:18px}}</style>
<rect width="1120" height="470" fill="#f2f4ef"/>
<text x="35" y="43" font-size="25" font-weight="bold">{label}</text>
<text x="35" y="71" class="small">Conceptual envelope only · not measured YAM CAD · dimensions in mm</text>
<rect x="55" y="170" width="83" height="139" rx="7" fill="#becac6"/>
<rect x="155" y="197" width="95" height="88" rx="7" fill="#a7c6c0" stroke="#376e68" stroke-width="2"/>
<rect x="178" y="218" width="48" height="14" rx="6" fill="#f2f4ef"/>
<rect x="178" y="254" width="48" height="14" rx="6" fill="#f2f4ef"/>
<path d="M265 190 L362 190 L620 250 L620 261 L360 291 L265 291 Z" fill="#dae5df" stroke="#376e68" stroke-width="2"/>
<path d="M450 278 L579 264" stroke="#c88d52" stroke-width="7"/>
<path d="M453 281 Q385 345 216 333" fill="none" stroke="#c88d52" stroke-width="2" stroke-dasharray="6 5"/>
<text x="58" y="343" class="small">Fixed mount</text><text x="167" y="369" class="small">Force element</text>
<text x="336" y="159" class="label">Thin replaceable finger</text>
<text x="346" y="390" class="small">Finger length input: {length:g}</text>
<text x="346" y="416" class="small">Nose thickness input: {d["nose_thickness_mm"]:g}</text>
<text x="724" y="151" class="label">Local pad seat</text>
<rect x="700" y="188" width="148" height="192" rx="9" fill="#e7e2d1" stroke="#a59a7c"/>
{"".join(grid)}
<text x="720" y="405" class="small">{cols} columns × {rows} rows</text>
<text x="875" y="218" class="small">Face: {width:g}</text>
<text x="875" y="249" class="small">Pad length: {d["pad_length_mm"]:g}</text>
<text x="875" y="280" class="small">Pitch: {d["cell_pitch_mm"]:g}</text>
<text x="875" y="311" class="small">Border: {d["pad_border_mm"]:g}</text>
<text x="875" y="351" class="small">{result["taxels"]} proposed taxels</text>
<text x="35" y="451" class="small">All mounting geometry, structural behavior, routing, and sensor performance require separate verification.</text>
</svg>'''
