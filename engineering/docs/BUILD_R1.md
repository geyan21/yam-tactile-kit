# Build R1: two nail cells and four pad cells

**This is a hand-assembled prototype recipe.** The cut sheet is dimensioned tooling, not a routed production FPC. Build three identified specimens before judging repeatability.

## Parts and orientation

Download `r1_cut_sheet.pdf` for actual-size A4 printing, or the editable `r1_cut_sheet.svg`, plus the nail-cover mold, four saddle molds, and mounting fit gauge. Verify the sheet's 20 mm scale. STEP is editable CAD; STL is the print export. The saddle witnesses show the cast part shape for inspection. They are not rigid parts to install on the soft finger.

The printed molds stand on their broad flat bottoms. Use PETG and 0.12 mm layers for tooling as a starting process. Check the actual cavity depth and surface finish. A 0.4 mm cast cavity is sensitive to first-layer and top-surface error; shim or remake a tool that is outside ±0.05 mm.

The four pad channels, from tip toward root, are CH2, CH3, CH4, CH5, each 13.00 mm wide. Their exact cut lengths are printed on the generated cut sheet and stored in `r1_manifest.json`. The development follows the nominal laminate neutral plane; extra adhesive changes that plane. Fit the serrated back of each saddle to the corresponding region shown in the section drawing. Do not stretch a saddle to make it fit a different region.

## Make the cells

1. Cut two copper electrodes and one separate conductive-film island for each channel. The orange outlines are the electrode active regions. The blue outlines are the slightly larger conductive-film islands. The outer black outline is the insulating carrier.
2. Put each copper electrode on the adhesive side of its polyimide backing, with its bare copper face exposed toward the conductive film. Use 25–35 µm bare copper foil. Conductive adhesive is not required in the sensing interface.
3. Attach a fine insulated lead to the proximal end of each copper electrode before sandwiching it. Add a 100 kΩ 0603 resistor across the two foil terminals at the cell end of the leads. Keep that resistor and both solder joints outside the loaded area and cover them with insulating tape. Route them onto a small proximal carrier extension; do not put a solder bump under a nail tip.
4. Stack backing / copper / conductive film / copper / backing. The two copper faces oppose one another. No adhesive, paint, or silicone belongs between copper and conductive film.
5. Seal the perimeter without squeezing the active area permanently. Keep all six conductive-film islands separate. A single continuous sheet would create unintended electrical paths.
6. Measure resistance while loading and unloading each cell gently. The parallel resistor limits the unloaded terminal resistance to about 100 kΩ. Reject a permanently shorted cell, a broken lead, or a cell that does not recover.

The nominal electrical laminate allowance is 0.30 mm. Actual foil, backing, seam, and solder thickness must be measured. A thin point cell may require a different pull-down resistor; keep the specified 10 kΩ during the first comparison, then document any change and recalibrate.

## Cast and attach

Use Dragon Skin 10 Slow for the first saddle batch. Use the material instructions for mixing and cure. Fill the narrow mold cavity completely, remove trapped bubbles, strike the exposed end flush, and demold only after the documented cure. Inspect each thin edge and tooth feature under magnification.

The saddle's mold depth defines its 13 mm width. Its curved cavity defines the contact profile. The back locates on the original serrations; the smooth front supports the laminate. Start the bond study with [Sil-Poxy](https://www.smooth-on.com/products/sil-poxy/), using separate silicone-to-TPU, silicone-to-PETG, and silicone-to-polyimide coupons. Its manufacturer gives a 24-hour full cure and recommends a suitability test. Bonding to these exact printed substrates is unverified. Record the bond-line thickness. Ordinary acrylic tape must not be assumed to bond cured silicone reliably.

Use a very thin perimeter bond to retain the cell on the saddle and a 0.40 mm cast silicone cover over it. Keep a removable seam outside the contact area.

For the nail, build **N0 first**: the sealed 0.30 mm insulating laminate with a thin non-foam acrylic transfer adhesive film and no additional silicone cover. Use a 0.05–0.10 mm mounting film, record its grade, and follow its surface-preparation and dwell instructions. The nominal addition is about 0.40 mm with a 0.10 mm bond; the outer insulating backing is the contact face. No copper may remain exposed. Thick foam mounting tape defeats this thin-tip version.

Compare **N1** on a separately identified specimen: add the 0.40 mm forked silicone cover, giving a nominal 0.80 mm addition. Trim it without bridging the central notch. This tests the friction/wear tradeoff against N0's thinner profile.

Adhesive and seam choices can exceed these allowances. **Measured installed thickness, opening loss, and thin-object task results decide whether either stack is acceptable.** No thickness tolerance or wear lifetime has yet been demonstrated. Record the nail variant and recalibrate when changing it.

## Route and retain wiring

Use two insulated leads per cell, then join the six excitation leads at the readout board. Route the bundle along the rigid PETG rails toward the root. Add local slack beside every compliant saddle. Anchor to rigid PETG before the cable exits the finger; keep wire, adhesive, and ties off the active nail and compliant struts.

Disconnect at the root to change the disposable skin. Photograph routing and record removal time. During a full passive bend, no lead should go taut, rub a sharp edge, or pull a saddle away from its seat.

## Fit acceptance before force tests

Compare each silhouette with the original finger. Check that the six zones respond individually, each returns near its unloaded value, and the same zones still respond after bending and reinstalling the finger. Apply a probe to the cover edges and the spaces between cells and map missed contacts. Do not report total grip force from contacts the sensor does not cover.
