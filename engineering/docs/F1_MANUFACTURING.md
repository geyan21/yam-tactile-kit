# F1 R4 manufacturing and assembly contract

The tactile sensor is **0.10 mm pressure-sensitive conductive film between
two custom flexible electrode sheets at each of six sites**. It is not an
off-the-shelf ADC board. Use one pair on each nail prong and one pair on each
of the four TPU regions. The two nail sites each provide eight electrical
locations; the four TPU sites each provide twelve. The notch remains open.

R4 retains R3's routed copper, contact map, interface PCB and carrier. It adds
the finished terminal construction, two rear-coverlay reliefs, plated-stack
allowance, retained silicone covers and fitting bases. Earlier R2, R3 and
13 mm cover attempts remain historical records. They must not be mixed with
the current 14 mm TPU covers and bases.

This is an experimental manufacturing contract. No specimens have been made
or measured here. The connector's internal seating datum, physical adhesion
and moving-TPU tail behavior still need the first assembly checks below.

## Order and make these parts

| Item per finger | Quantity | Material or selected part |
|---|---:|---|
| Fitted electrode flexes | 12 distinct | `f1_ch0_columns` through `f1_ch5_rows`; matching R4 files |
| Pressure-film islands | 6 distinct | Identified 0.10 mm conductive pressure film; reference material Adafruit 1361; record supplier, lot and actual thickness |
| Protective covers | 6 distinct | Smooth-On Dragon Skin 10 Slow; 0.10 mm nail roof and 0.40 mm TPU roof are nominal mold targets |
| Compliant fitting bases | 4 distinct | Dragon Skin 10 Slow; use current 14 mm wide R1-derived fitting geometry |
| Terminal PI stiffeners | 14 pieces | 0.200 mm PI: ten single pieces and two pairs of segmented nail-row pieces |
| Stiffener adhesive pieces | 14 pieces | 0.050 mm nominal 3M 467MP transfer adhesive; qualify the actual lamination and finished tongue thickness |
| Silicone-to-frame/base/foil bond | As required | Sil-Poxy, nominal 0.050 mm cured bond where modeled; qualify actual TPU, printed frame and PI surfaces on coupons |
| Fixed finger interface PCB | 1 | Checked R3 board, matching 42-component BOM; twelve FH12-6S-1SH(1)(98) connectors |
| Carrier and forming tools | 1 carrier, 6 forms | Use matching R3 carrier and current layer-assembly forms; smooth the tooling surfaces |
| Registered cover/base molds | 10 pairs | Six cover molds and four fitting-base molds; use the supplied bolt/dowel coordinates |
| Wrist readout PCB | 1 | Checked F1 wrist board and its complete component BOM |
| Controller | 1 | Raspberry Pi Pico RP2040, non-W, fitted to the wrist board sockets |
| Wrist cable | 1 inspected candidate | Molex 150200545, 50-way, 0.5 mm pitch, 152 mm, same-side contacts; limitations below |

The interface and wrist component CSVs are the purchasing lists for the
electronics. The table above does not replace their passive-component,
connector and mounting details. Use the full repository for host software.
No printed sensor or connector envelope replaces the corresponding purchased
electrical part.

## Flexible-circuit drawing

Order **one copy of each of the twelve distinct shapes per finger**. The
electrically active F.Cu faces the conductive film on both layers: inward
for the upper row foil, outward for the lower column foil. Each curved layer
has its own developed outline; the row and column cuts are not interchangeable.

| Feature | Required construction |
|---|---|
| Core | 25 µm adhesiveless polyimide; do not add an unaccounted copper-to-core adhesive |
| Copper | 35 µm rolled-annealed copper, actual routed geometry retained |
| Copper layers | Two only on CH0 rows and CH1 rows; one physical copper layer on the other ten foils |
| Coverlay | 50 µm total modeled thickness per covered face, including its adhesive; use the supplied openings |
| Exposed metal finish | Nickel 1–5 µm, nominal 3 µm; gold at least 0.2 µm; confirm the actual process with the flex fabricator |
| Active film | Nominal 100 µm; an actual measured thickness is required before final lamination |
| Finished connector tongue | 0.25–0.35 mm; proposal is 0.3132 mm nominal including finish, 200 µm PI and 50 µm adhesive |
| Cut tongue width | 7.00 mm nominal; acceptable 6.88–7.07 mm |
| Contacts | Six positions, 1.00 mm pitch; 0.65 mm nominal width, ±0.10 mm; preserve actual unused contacts |
| Contact and support length | At least 3.5 mm exposed and 4.5 mm supported, measured from the physical tip |
| Rear relief, CH0/CH1 rows only | Remove rear coverlay for 6.4 mm from the tip; use the checked R4 B.Mask opening |
| Back-copper clearance at relief | Nominal minimum 0.200 mm includes plated annuli; delivered minimum 0.150 mm, including registration |
| Stiffeners on ten one-layer foils | One 8 mm piece with matching 50 µm adhesive |
| Stiffeners on two nail-row foils | Separate 0–6.4 mm tip and 6.5–8.0 mm transition pieces; retain the 0.1 mm separation |

The nail-row rear feed/via area has a backing-layer step. Do not bridge it
with one flat stiffener and silently increase the tongue thickness.
The short transition piece supports the terminal via region. Keep that
region stationary after seating; the gap is not a fatigue hinge.

KiCad uses a two-slot copper representation even for the ten physical
single-layer foils. **Use the per-foil `FPC_STACK.json` and this construction
drawing.** An empty B.Cu slot is not a second physical copper sheet, and
these files do not specify a generic FR4 PCB. The supplied native DRC retains
the shared, unsoldered coverlay-window findings; copper shorts and missing
connections are not waived.

The development exports retain their original warnings. This contract
supplies the missing proposed finished stack; it does not turn an unmeasured
connector interface into a qualified mating pair. First make a nail-row
and a single-layer terminal coupon using the actual materials, finish and
cutting process. Measure width, thickness, exposed/support lengths, contact
orientation and seated position in the actual Hirose part. Confirm the
12-tail fit using the carrier before authorizing a larger flex batch.

## Contact stack and location

Read the stack from the finger toward the object:

1. Nail surface, or the cast compliant base on the TPU.
2. Nominal 50 µm insulating mounting bond and lower column foil.
3. Lower exposed contact finish, 100 µm pressure-film island, upper contact finish.
4. Upper row foil, with its active copper toward the film.
5. Separately cast silicone cover, bonded at the peripheral foot.

The nominal nail addition is **0.4614 mm**. The TPU stack reaches
**0.7264 mm above the R1 smoothed fitting datum**; the variable base below
that datum is additional. These are uncompressed geometry values.
The TPU foil is 13 mm wide, its cover/base 14 mm, and the source insert
15 mm. Both side skirts therefore land on the fitting base.

Keep all adhesive out of the active film-to-metal interfaces. The edge
bond, cover skirt and film are parallel mechanical load paths, so response
near edges can differ from central loading. Cast and inspect the thin nail
roofs before committing a complete finger.

## Assembly sequence

1. Verify the carrier on the actual frame and installed gripper drive.
   The exact drive model is still unidentified. Check jaw travel, broad-object
   access and cable clearance using the unpowered assembly.
2. Fabricate the PCBs and terminal coupons. Inspect the native pin tables,
   all supply rails, shorts and actual connector seating before fitting film.
3. Cast a bond coupon and small cover sample with the actual tooling,
   release agent, PI, printed frame and TPU. Record cure, bond thickness,
   peel/flex behavior and any film-contact contamination. Failed coupons
   remain results.
4. Cast the four fitting bases and six covers in their own molds. The
   side overflow paths are deliberate. Trim flash without cutting the
   skirts or widening the foil ports. Measure the cured thicknesses.
5. Form each foil smoothly on its own layer form. The current bend reference
   radius is 2.5 mm; do not crease it. Laminate the terminal stiffeners and
   measure the completed tongues.
6. Bond the bases onto the TPU, and each column foil onto its source or base.
   Register the identified film island and row foil on the supplied form.
   Photograph polarity, site labels, overlaps and electrode alignment.
7. Bond each cover's peripheral foot to the source or base. Admit both
   necks through the specified end port. Use a small qualified flexible
   sealing bead at the static port edges. Keep adhesive away from the
   film and free bend.
8. Seat the twelve identified foils in their matching connectors while
   supporting the removed PCB. Close the latches fully. Retain each
   reinforced terminal section against movement with a qualified removable
   flexible bond/fixture on the stationary carrier side; inspect clearance
   from every neighboring connector and component.
9. Inspect all twelve tails together, including both PCB faces. The nominal
   3 mm motion allowance is an assumption, not demonstrated slack at 20 N.
   Record actual tail motion with unpowered incremental jaw/TPU displacement.
   Keep testing on the fixed bench if a tail tightens, rubs or buckles.
10. Connect the inspected wrist cable, verify continuity with power off, then
    run the electrical and physical workflow in `F1_TESTING.md`.

The beads and physical strain relief are process details requiring inspection;
their cured shapes are not collision-qualified by the nominal CAD. A nominal
clearance report does not qualify adhesion, sealing, loaded motion or fatigue.

## Wrist cable acceptance

Molex 150200545 is a gold-finished comparison candidate, not an established
substitution for the historical tin-finished cable. Its 0.27 ±0.05 mm body
needs a fresh physical routing check. Manufacturer end thickness is
0.30 ±0.05 mm, but the available drawings permit exposed and reinforced
lengths below the initial Hirose targets. The documented plating minima
also differ.

Inspect the delivered strip and support lengths against the actual connector
drawing and verify seating/contact resistance. Reject an unsuitable cable;
obtain a cable built to the connector's complete terminal contract instead.
Do not compensate by forcing the latch. Preserve the measured cable identity.
The inspection pose uses **wrist pin n → fanout pin 51−n**; verify every
conductor with the supplied continuity checklist.

Primary references:
[Hirose selected connector](https://www.hirose.com/en/product/p/CL0528-0030-8-98),
[Hirose FH12 catalog](https://www.hirose.com/en/product/series/FH12),
[Molex 150200545](https://www.molex.com/en-us/products/part-detail/150200545),
[Molex sales drawing](https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/salesdrawingpdf/150/15020/150200545_sd.pdf).
