# Reproduce the design lab

This guide reproduces the digital work delivered with YAM Tactile Kit: a design review, an editable visualization, envelope calculations, a synthetic calibration exercise, and a portable website. Physical replication follows the separate hardware guide and requires measurements and component selection that are not yet available.

## 1. Obtain a standalone checkout

Download the source ZIP from the website and extract it. The top directory is `yam-tactile-kit/`. A GitHub checkout, when published, has the same source layout. A local Git bundle is also produced by `scripts/export_git.py`.

Do not run from inside the surrounding Flex-π repository. Change into the kit directory containing this README and `VERSION`.

## 2. Build without installing packages

Use Python 3.10 or newer. The verified Linux interpreter is `/usr/bin/python3`; use the explicit interpreter path on your own machine.

```sh
/usr/bin/python3 scripts/reproduce.py
/usr/bin/python3 -m unittest discover -s tests -v
```

The builder reads the checked-in example design and synthetic CSV. It validates units/ranges, computes the summary, writes the SVG, fits the calibration model, renders this documentation into HTML, and creates the source ZIP and hash manifest. It does not fetch upstream repositories or contact a robot.

For the checked-in example, expect 2 columns × 8 rows, 16 taxels, 10 electrode nets, a 4×16 mm active-cell envelope, 0.8 mm of estimated opening loss, and 400 N/mm minimum adapter stiffness from the illustrative budget. The recovered idealized force is 5 N. With the example 1.5 load factor, static support requires approximately 12.26 N per jaw. These numbers are calculations from the example inputs, not device measurements.

## 3. Open the website

```sh
/usr/bin/python3 scripts/serve.py --port 8766
```

Open `http://127.0.0.1:8766/` in a browser on the same machine. The script prints its address and process identity and writes an execution record when it stops. Ctrl+C in its terminal stops that server. If the port is occupied, select a different port; do not stop another service.

For offline use, open `build/site/index.html` directly. The page uses local scripts and embedded data; it has no CDN fonts, analytics, account dependency, or network data fetch. External research links need a network connection.

The build also writes `build/yam-tactile-site.zip`. Extract this complete prebuilt site to another machine and open its `index.html`; keep the included assets and downloads beside it. No Python installation is needed just to view that prebuilt copy.

On a managed host, view the local website through the approved remote-access workflow. No additional tunnels are part of these instructions.

## 4. Use the design lab

The assembly view highlights the replaceable finger, proximal sensor module, and optional pressure strip. The explode control separates those conceptual parts for inspection; it does not represent a real assembly tolerance.

Change the contact-face width, pad length, border, and cell pitch to see the whole-cell envelope. The drawing reserves one pitch-wide envelope per cell. It does not route copper or account for supplier-specific keepouts. An empty grid means no complete cell fits after the assumed border.

Move the contact point to see why one bending measurement depends on the contact lever arm. In the ideal model, the difference of two moment measurements divided by their spacing returns the same applied normal force. Change the end moment to see its cancellation. Noise, cross-axis sensitivity, and structural behavior are not simulated.

Export the current settings with **Export design JSON**. Import the file later to restore them. The browser does not modify the repository's example file.

## 5. Make a reproducible variant

Save a copy of the exported JSON in `examples/`, then build to a separate output directory:

```sh
/usr/bin/python3 scripts/reproduce.py \
  --design examples/my-design.json \
  --output build/my-design
```

Serve that generated site:

```sh
/usr/bin/python3 scripts/serve.py \
  --directory build/my-design/site \
  --port 8767
```

Use `geometry_status: "measured_inputs"` only when the entered dimensions have actually been measured. This status does not mean the design is structurally validated. Preserve the raw measurements and source CAD hash in the hardware measurement record.

The normal source download always contains the checked-in source/examples. A generated site's **Current build inputs** download separately records the exact design and calibration input used for that build. The source ZIP also includes those inputs in `reproduction/`, so an extracted custom build can be recreated without an external file.

## 6. Reproduce the calibration exercise

```sh
/usr/bin/python3 scripts/calibrate.py \
  --input examples/calibration.synthetic.csv \
  --output build/calibration-report.json
```

Inspect the report's `dataset_kind`, coefficients, held-out positions, RMSE, and maximum error. The checked-in exercise uses synthetic data and must remain labeled that way. Run the same script with a measured-data CSV only after collecting reference loads according to the calibration guide.

Rebuild the website with that chosen input:

```sh
/usr/bin/python3 scripts/reproduce.py \
  --calibration path/to/recorded-calibration.csv
```

Publication includes the supplied calibration CSV in the downloadable archive. Use only a dataset intended for sharing in a public build.

## 7. Verify the browser and the archive

If Chrome or Chromium is installed, pass its explicit path:

```sh
/usr/bin/python3 scripts/verify_browser.py \
  --browser /usr/bin/google-chrome
```

The verifier checks real DOM interactions, restores the example, checks responsive layouts, and saves screenshots under `build/browser-review/`. It uses its own short-lived local HTTP server and browser, with saved command/PID records.

Mobile DOM checks use a 375 px viewport. The mobile review image uses a 390 px iframe inside a wider browser window to avoid desktop Chrome's minimum-window-width behavior.

The force-component image uses a temporary review page that hides preceding sections while retaining the real component and application code. The interaction checks separately verify navigation to the actual force section.

The source archive has deterministic file ordering and ZIP timestamps. Its SHA-256 manifest covers the source contents and the current build's reproduction inputs. Runtime records and Git metadata are not part of this reproducibility claim. Unit tests extract the archive, rebuild it in another directory, and compare the core generated outputs.

## 8. Publish with GitHub Pages

The source includes `.github/workflows/pages.yml`. It builds and tests the site, uploads `build/site`, and deploys from the `main` branch. Pull requests run the build/tests without publishing.

For the intended GitHub repository, select **Settings → Pages → Build and deployment → Source: GitHub Actions**, then push the source to `main` or run the Pages workflow. GitHub provides the deployed URL in the workflow's `github-pages` environment. The workflow sets the repository link from the actual GitHub repository identity.

The workflow follows GitHub's documented custom Pages deployment structure. Account permissions and Pages availability depend on the repository/account configuration; a private source repository does not by itself establish that a Pages site is private.

`scripts/github_status.py --owner YOUR-ACCOUNT` is an optional read-only publication check. It uses standard `GH_TOKEN` / `GITHUB_TOKEN` authentication or Git's existing `github.com` credential helper and reports only the account/repository state. It does not log credentials, create a repository, or modify GitHub. Use an authorized connection/login before publication; do not paste credentials into a chat or commit them.

Sources: [GitHub custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [GitHub Pages visibility](https://docs.github.com/en/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site).

## Troubleshooting

If JSON validation fails, keep all documented numeric fields, use finite numbers, place contact beyond both stations, and keep the pad within the finger length. The validator reports the specific field.

If the calibration is rank-deficient, vary the load position and use independent training/test samples. Repeated observations of a single load case cannot determine two independent channel sensitivities.

If the browser verifier cannot start Chrome inside a restricted execution sandbox, preserve the failure record and use the host's authorized execution mechanism. Do not disable security monitoring or add remote-debugging/tunneling mechanisms.

If Pages deployment fails, inspect that workflow's error and the repository's Pages source/environment settings. A successful local build is not proof of a successful deployment.
