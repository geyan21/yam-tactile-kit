# YAM Tactile Kit

A reproducible design review and interactive lab for a thin, replaceable YAM finger with force sensing at its base and an optional surface pressure strip.

**Release 0.1.0 reproduces a concept, calculations, visualizations, and a calibration exercise. No YAM hardware has been fabricated, fitted, or qualified by this project.** The example geometry is illustrative. The supplied calibration data is synthetic.

## Reproduce the release

Requirements: Python 3.10 or newer; a modern web browser. There are no third-party Python packages, JavaScript packages, network downloads, or build-service accounts required.

Run these commands from this repository's root. `/usr/bin/python3` is the interpreter used for the verified Linux build. On another system, substitute the explicit path to your Python 3 interpreter.

```sh
/usr/bin/python3 scripts/reproduce.py
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 scripts/serve.py --port 8766
```

Open `http://127.0.0.1:8766/`. The server listens on this machine only. Use the host's approved remote desktop or VPN workflow when working remotely; this project does not create a tunnel.

The website is also usable offline by opening `build/site/index.html`. Stop the foreground web server with Ctrl+C in its own terminal.

The build creates:

| Output | Purpose |
| --- | --- |
| `build/site/index.html` | Interactive assembly, pad-layout and force-path visualization |
| `build/site/guide.html` | Complete replication and hardware-development guide |
| `build/yam-tactile-site.zip` | Prebuilt offline website; extract and open `index.html` without running Python |
| `build/design-summary.json` | Auditable envelope and force-budget calculations |
| `build/finger-concept.svg` | Parameterized, dimension-labeled concept drawing |
| `build/calibration-report.json` | Fit and held-out evaluation of the synthetic calibration exercise |
| `build/site/downloads/yam-tactile-kit.zip` | Complete portable source repository |
| `build/site/downloads/source-manifest.json` | SHA-256 for every file in the source archive |
| `build/records/` | Timestamped execution records, including commands and process identities |

The archive contains all source, documentation, templates, example data, and tests. Generated output and execution logs are separate from source. The archive's own manifest is excluded from its list of hashed source files.

## Start here

- [Replication guide](docs/REPLICATE.md): commands, expected results, customization, offline use, and export.
- [Hardware development guide](docs/HARDWARE.md): measurement, mechanics, components, electrical interface, assembly, and service.
- [Calibration guide](docs/CALIBRATION.md): CSV format, fitting, holdout design, and interpreting the synthetic example.
- [Validation plan](docs/VALIDATION.md): physical tests required before claiming a usable gripper.
- [Original design review](docs/DESIGN_REVIEW.md): rationale and primary references.
- [Scope and provenance](docs/SCOPE.md): implemented artifacts, unverified hardware, and upstream licensing.

## Change the example

Copy `examples/design.example.json`, edit the values, and rebuild:

```sh
/usr/bin/python3 scripts/reproduce.py --design examples/design.example.json
```

The website supports editing the same parameters and importing/exporting that JSON format. Website changes stay in the browser until exported. They do not rewrite files on disk.

Record your actual finger measurements separately in `hardware/measurements.template.json`. Its unknown fields are deliberately `null`; the builder never fills them from the illustrative design.

## Calibrate recorded data

```sh
/usr/bin/python3 scripts/calibrate.py \
  --input examples/calibration.synthetic.csv \
  --output build/calibration-report.json
```

Use the documented CSV format for real measurements. The analysis fits two raw channels to reference normal force and evaluates a separate held-out set. It does not connect to a sensor, command a robot, or make a measured sensor production-ready.

## Optional browser verification and Git export

With a local Chrome/Chromium executable:

```sh
/usr/bin/python3 scripts/verify_browser.py --browser /usr/bin/google-chrome
```

This opens only the local generated website, checks interactions, and saves desktop/mobile screenshots and a result record. It starts and closes its own temporary HTTP server and browser. It does not use a remote debugging port.

With Git installed:

```sh
/usr/bin/python3 scripts/export_git.py --git /usr/bin/git
```

This creates a Git bundle from a fresh temporary copy of the archive. It does not commit to or change any surrounding repository. To obtain a separate repository:

```sh
/usr/bin/git clone build/yam-tactile-kit.bundle yam-tactile-kit-copy
```

## What to build physically

The recommended first mechanical prototype retains the working thin finger and adds a characterized force element at its mount. Evaluate a flat FlexiTac coupon separately before a custom narrow FPC. Exact mounting geometry, force-element selection, PCB layout, protective structure, and qualification remain hardware development work. The BOM is a component/specification checklist with unresolved part selections, not an order-ready kit.

No external sensor firmware, FPC fabrication files, or manufacturer CAD is redistributed here. See `docs/SCOPE.md` and the linked primary sources before using an upstream design commercially.
