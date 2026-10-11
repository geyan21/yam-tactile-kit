"""Render separate, consistently structured design pages from the local catalog."""

import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
REQUIRED=("id","slug","title","group","status","status_detail","summary","signal",
          "best_for","tradeoff","sensors","placement","schematic","resources","missing","next_steps","related")


def esc(value):
    return html.escape(str(value),quote=True)


def load_catalog():
    data=json.loads((ROOT/"engineering/design_catalog.json").read_text())
    groups={row["id"] for row in data["groups"]}
    ids=set();slugs=set()
    for item in data["designs"]:
        if any(key not in item for key in REQUIRED):
            raise ValueError("Incomplete design page")
        if item["id"] in ids or item["slug"] in slugs or not re.fullmatch(r"[a-z0-9-]+",item["slug"]):
            raise ValueError("Duplicate or unsafe design identifier")
        if item["group"] not in groups or len(item["schematic"])!=4:
            raise ValueError("Invalid design category or schematic")
        if not item["sensors"] or any(len(row)!=3 for row in item["sensors"]):
            raise ValueError("Every design needs explicit sensor/placement rows")
        if not item["missing"] or not item["next_steps"]:
            raise ValueError("Design readiness must be explicit")
        ids.add(item["id"]);slugs.add(item["slug"])
    for item in data["designs"]:
        if set(item["related"])-ids:
            raise ValueError(f"Unknown related design for {item['id']}")
    return data


def link(label,target,**attributes):
    extra=' target="_blank" rel="noopener noreferrer"' if target.startswith("https://") else ""
    extra+="".join(f' {esc(k.replace("_","-"))}="{esc(v)}"' for k,v in attributes.items())
    return f'<a href="{esc(target)}"{extra}>{esc(label)}</a>'


def schematic(item):
    """A functional diagram, intentionally not a fabrication drawing."""
    import textwrap
    blocks=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 260" role="img" aria-labelledby="title desc">',
            f'<title id="title">{esc(item["title"])} — sensing principle</title>',
            '<desc id="desc">Functional signal or load path, with four labeled steps. This is not dimensional CAD.</desc>',
            '<rect width="1000" height="260" fill="#f5f8f4"/>',
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#537872"/></marker></defs>',
            '<g font-family="sans-serif" fill="#203f46">',
            '<text x="26" y="36" font-size="20" font-weight="bold">How this design senses</text>']
    for i,label in enumerate(item["schematic"]):
        x=26+i*247
        blocks.append(f'<rect x="{x}" y="71" width="205" height="113" rx="10" fill="{("#e7edd9","#dcebe5","#e4e0ef","#e8edf0")[i]}" stroke="#97aaa6"/>')
        blocks.append(f'<text x="{x+16}" y="98" font-size="13" font-weight="bold">{i+1:02d}</text>')
        for j,line in enumerate(textwrap.wrap(label,width=23)):
            blocks.append(f'<text x="{x+102.5}" y="{127+22*j}" text-anchor="middle" font-size="16">{esc(line)}</text>')
        if i<3:
            blocks.append(f'<path d="M{x+210} 127H{x+239}" stroke="#537872" stroke-width="2" marker-end="url(#arrow)"/>')
    blocks.append('<text x="26" y="221" font-size="14">Functional illustration only. Use the design page for sensor selection, placement and available files.</text></g></svg>')
    return "\n".join(blocks)+"\n"


def navigation(catalog,active=""):
    groups=[]
    for group in catalog["groups"]:
        items=[item for item in catalog["designs"] if item["group"]==group["id"]]
        if not items:
            continue
        links="".join(link(item["title"],item["slug"]+".html",
                           **({"aria_current":"page","class":"active"} if item["slug"]==active else {})) for item in items)
        groups.append(f'<div class="design-nav-group"><p>{esc(group["title"])}</p>{links}</div>')
    return "".join(groups)


def shell(title,body,catalog,active="",scripts=""):
    nav=navigation(catalog,active)
    return f'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · ENPIRE tactile</title>
<link rel="stylesheet" href="assets/style.css"><link rel="stylesheet" href="assets/design-pages.css">{scripts}
</head><body><a class="skip" href="#design-document">Skip to design</a>
<header><a class="brand" href="index.html">ENPIRE <b>TACTILE</b></a><nav aria-label="Main">
<a href="designs.html">Designs</a><a href="sensors.html">Sensor map</a><a href="architecture.html">Study</a>
<a href="https://github.com/geyan21/yam-tactile-kit">GitHub ↗</a></nav></header>
<main class="design-page-layout"><aside class="design-page-nav" aria-label="Design directory">
<a class="all-designs-link" href="designs.html">← All designs &amp; status</a>{nav}
<a href="guide.html">Complete printable guide</a></aside>
<div class="design-page-main"><details class="design-mobile-nav"><summary>Choose another design</summary>
<a href="designs.html">All designs &amp; status</a>{nav}</details>
<article id="design-document">{body}</article></div></main>
<footer><a href="designs.html">All separate design pages</a><a href="downloads/enpire-engineering-kit.zip" download>Complete portable packet ↓</a></footer>
</body></html>'''


def cad_table(item):
    group=item.get("cad_group")
    prototype=item.get("prototype_cad_group")
    if not group and not prototype:return ""
    if prototype:
        plan=json.loads((ROOT/"engineering/prototypes"/prototype/f"{prototype}_manifest.json").read_text())
        prefix="prototypes/"+prototype+"/"
    else:
        plan=json.loads((ROOT/"engineering/release"/group/f"{group}_manifest.json").read_text())
        prefix="" if group=="r1" else group+"/"
    rows=[]
    for part in plan["parts"]:
        kind="Reference envelope only" if part.get("kind")=="reference_only" else "Prototype part/tooling"
        rows.append('<tr><td data-label="Part">'+esc(part["id"])+'</td><td data-label="Purpose">'+esc(part["purpose"])+"<small>"+kind+'</small></td><td data-label="Files">'+
                    link("STEP ↓","downloads/"+prefix+part["step"])+link("STL ↓","downloads/"+prefix+part["stl"])+"</td></tr>")
    return '<details class="design-cad-list"><summary>Individual CAD files for '+esc(item["id"])+'</summary><div class="table-scroll"><table><thead><tr><th>Part</th><th>Purpose</th><th>Files</th></tr></thead><tbody>'+"".join(rows)+"</tbody></table></div></details>"


def design_content(item,catalog,viewer=True):
    key=item["slug"]
    sensor_heading="Exact sensors and where they go" if item["group"]=="prototype" else "Proposed sensors and placement"
    visual=item.get("visual")
    visual_html=""
    if visual:
        visual_html=f'<figure class="design-main-figure"><a href="{esc(visual["path"])}"><img src="{esc(visual["path"])}" alt="{esc(visual["alt"])}"></a><figcaption>{esc(visual["caption"])} {link("Open full size ↗",visual["path"])}</figcaption></figure>'
    else:
        visual_html=f'<figure class="design-main-figure"><a href="assets/design-schematics/{key}.svg"><img src="assets/design-schematics/{key}.svg" alt="{esc(item["title"])} functional diagram"></a><figcaption>Conceptual sensing path. No ENPIRE placement dimensions are finalized for this approach. {link("Open full size ↗","assets/design-schematics/"+key+".svg")}</figcaption></figure>'
    placement_html=""
    placement=item.get("placement_visual")
    if placement:
        placement_html=f'<figure class="design-main-figure"><a href="{esc(placement["path"])}"><img src="{esc(placement["path"])}" alt="{esc(placement["alt"])}" loading="lazy"></a><figcaption>{esc(placement["caption"])} {link("Open full size ↗",placement["path"])}</figcaption></figure>'
    sensors="".join("<tr>"+"".join(f'<td data-label="{label}">{esc(cell)}</td>' for label,cell in zip(("Part / quantity","Sensor choice","Placement"),row))+"</tr>" for row in item["sensors"])
    resources="".join(f'<tr><td>{esc(kind)}</td><td>{link(label,href)}</td></tr>' for kind,label,href in item["resources"])
    missing="".join(f"<li>{esc(value)}</li>" for value in item["missing"])
    steps="".join(f"<li>{esc(value)}</li>" for value in item["next_steps"])
    by_id={value["id"]:value for value in catalog["designs"]}
    related="".join(link(by_id[value]["title"],by_id[value]["slug"]+".html",**{"class":"button"}) for value in item["related"])
    viewer_html=""
    if viewer and item.get("viewer_model"):
        viewer_html=f'''<details class="design-viewer-details" data-design-viewer>
<summary>Inspect the actual {esc(item["id"])} assembly in 3D</summary>
<div class="viewer-card"><div class="viewer-top"><strong>{esc(item["id"])} assembly</strong><button type="button" data-reset-design-view>Reset view</button></div>
<canvas class="design-canvas" tabindex="0" role="img" data-model-id="{esc(item["viewer_model"])}" aria-label="Interactive {esc(item["id"])} assembly; drag or use arrow keys"></canvas>
<div class="viewer-bottom"><label>Separate parts <input type="range" data-design-explode min="0" max="100" value="0"></label><span>Drag / arrow keys to rotate · scroll to zoom</span></div>
<div class="design-viewer-layers"></div><p class="design-viewer-note"></p></div></details>'''
    return f'''<div class="design-intro" data-design-id="{esc(item["id"])}" data-design-stage="{esc(item["group"])}">
<p class="design-breadcrumb"><a href="designs.html">All designs</a> / {esc(item["id"])}</p>
<span class="design-status {esc(item["group"])}">{esc(item["status"])}</span>
<h1>{esc(item["title"])}</h1><p class="design-summary">{esc(item["summary"])}</p>
<p class="design-stage-detail">{esc(item["status_detail"])}</p>
<p class="design-target">Shared project target: 20 N per finger. This page does not establish a hardware rating.</p></div>
<nav class="design-section-nav" aria-label="On this page"><a href="#{key}-sensors">Sensors &amp; placement</a>
<a href="#{key}-files">Files &amp; instructions</a><a href="#{key}-remaining">What remains</a></nav>
{visual_html}
<div class="design-facts"><div><h2>What it measures</h2><p>{esc(item["signal"])}</p></div>
<div><h2>Why consider it</h2><p>{esc(item["best_for"])}</p></div>
<div><h2>Main tradeoff</h2><p>{esc(item["tradeoff"])}</p></div></div>
<section id="{key}-sensors" class="design-section"><h2>{sensor_heading}</h2>
<p>{esc(item["placement"])}</p><div class="table-scroll"><table class="design-sensor-table">
<thead><tr><th>Part / quantity</th><th>Sensor choice</th><th>Placement</th></tr></thead><tbody>{sensors}</tbody></table></div>{placement_html}
{"<figure class='design-flow'><a href='assets/design-schematics/"+key+".svg'><img src='assets/design-schematics/"+key+".svg' alt='"+esc(item["title"])+" sensing principle'></a></figure>" if visual else ""}</section>
{viewer_html}
<section id="{key}-files" class="design-section"><h2>Available files and instructions</h2>
<div class="table-scroll"><table class="design-resource-table"><thead><tr><th>Type</th><th>Open / download</th></tr></thead><tbody>{resources}</tbody></table></div>
{cad_table(item)}</section>
<section id="{key}-remaining" class="design-section"><h2>What is not provided or proven yet</h2><ul class="design-missing">{missing}</ul>
<h2>Next steps for this design</h2><ol class="design-next">{steps}</ol></section>
<section class="design-related"><h2>Compare with</h2><div class="actions">{related}</div></section>'''


def catalog_content(catalog):
    cards=[]
    for group in catalog["groups"]:
        items=[item for item in catalog["designs"] if item["group"]==group["id"]]
        if not items:
            continue
        entries=[]
        for item in items:
            visual=item.get("visual",{"path":f'assets/design-schematics/{item["slug"]}.svg',"alt":item["title"]+" principle"})
            entries.append(f'''<a class="design-card" data-design-card="{esc(item["id"])}" data-stage="{esc(item["group"])}" href="{esc(item["slug"])}.html">
<div class="design-card-image"><img src="{esc(visual["path"])}" alt="{esc(visual["alt"])}" loading="lazy"></div>
<div class="design-card-copy"><span class="design-status {esc(item["group"])}">{esc(item["status"])}</span>
<h3>{esc(item["title"])}</h3><p>{esc(item["summary"])}</p><span class="design-card-action">Open this design →</span></div></a>''')
        cards.append(f'<section id="{esc(group["id"])}" class="design-catalog-group"><h2>{esc(group["title"])}</h2><p>{esc(group["description"])}</p><div class="design-card-grid">{"".join(entries)}</div></section>')
    counts={group["id"]:sum(item["group"]==group["id"] for item in catalog["designs"]) for group in catalog["groups"]}
    category_links="".join(
        f'<a href="#{group["id"]}">{counts[group["id"]]} {esc(group["title"].lower())}</a>'
        for group in catalog["groups"] if counts[group["id"]])
    return f'''<div class="design-intro"><p class="eyebrow">ONE PAGE PER DESIGN</p><h1>Choose a design.<br>See exactly what exists.</h1>
<p class="design-summary">Each page gives its purpose, sensor choice, placement, visuals, available files and remaining work.</p>
<p class="design-stage-detail">{counts["prototype"]} prototype packages have build files. Other approaches remain in development. No design is yet physically qualified through the 20 N per finger target. <a href="build-all.html">Follow the all-design build and comparison campaign →</a></p></div>
<nav class="design-section-nav" aria-label="Design categories">{category_links}</nav>'''+ "".join(cards)


def build_design_pages(site,catalog=None):
    catalog=catalog or load_catalog()
    directory=site/"assets/design-schematics";directory.mkdir(parents=True,exist_ok=True)
    for item in catalog["designs"]:
        (directory/f'{item["slug"]}.svg').write_text(schematic(item))
        scripts=('<script src="assets/data.js" defer></script><script src="assets/viewer.js" defer></script>'
                 '<script src="assets/design-viewer.js" defer></script>') if item.get("viewer_model") else ""
        (site/f'{item["slug"]}.html').write_text(shell(item["title"],design_content(item,catalog),catalog,item["slug"],scripts))
    (site/"designs.html").write_text(shell("All designs and readiness",catalog_content(catalog),catalog))
    (site/"assets/design-catalog.json").write_text(json.dumps(catalog,indent=2)+"\n")
    return catalog
