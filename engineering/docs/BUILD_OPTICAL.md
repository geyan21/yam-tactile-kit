# Build O1: fixed optics, compliant gel, thin nail

[O1 design page, sensor placement, 3D assembly and downloads](https://geyan21.github.io/yam-tactile-kit/optical.html).

O1 keeps the original nail and drive interface, replaces the opaque insert with a clear gel cartridge, and places a camera behind a fixed mirror. **The gel remains compliant; the camera, mirror backing and frame are rigid.** This separate alternative adds **32 mm of reach** and a larger root enclosure. All earlier designs remain available.

This is a digital prototype package. **No specimen has been assembled or tested. The 20 N per-finger value is the project target, not a hardware rating.**

## What to make and buy

Use the [complete O1 BOM](assets/prototypes/optical/bom.csv), [parts table](assets/prototypes/optical/parts.csv), and [prototype ZIP](downloads/o1-prototype.zip).

| Assembly | Selected part or material | Position |
|---|---|---|
| Optical tactile surface | Smooth-On Solaris clear silicone, 2.5 mm nominal normal thickness | Curved 13 mm-wide front pad; 16 mm rear flange retained by two clips |
| Visible markers | 42 black silicone-paint dots beneath a white silicone overcoat | Three columns × fourteen rows on the object-facing gel surface |
| Mirror | 0.20 mm reflective PET, 14 × 63.892 mm | Bonded flat to the integral rigid backing; reflective face toward gel/camera |
| Camera | Raspberry Pi Camera Module 3 Wide, visible-light IR-cut version | Root bay; rotated 180° about its optical axis |
| Illumination | Four Kingbright APT2012QBC/D blue LEDs | Small ring around the lens, retained by the camera-mounted carrier |
| Nail tactile cells | Two retained R1 N0 laminates | Separate left and right hard nail prongs; 0.4 mm nominal installed addition |
| Readout | Pi 4 Model B and Adafruit ADS1115 #1085 | Insulated bench installation; see the wiring page |

The PET mirror is a procurement specification, not a verified vendor ordering code. Accept its thickness, flatness, reflective-side orientation and image sharpness before cutting the final piece. Wrinkles, bubbles or a poor reflective surface invalidate the optical setup.

## Print and inspect the rigid parts

Print the frame, lid, two retaining clips and LED carrier in opaque rigid material. PETG is the first print candidate; actual stiffness and durability remain to be measured. Start with 0.12 mm layers and enough perimeters to make the narrow walls solid. Orient for accessible support removal through the open gel face and camera bay. Remove all supports and smooth the mirror backing before assembly.

Check the unchanged mounting bores, leading nail, clip seats, nut pockets, optical window and camera supports against the CAD. The user's installed drive model remains unidentified: test the complete passive stroke and mounting-tool access on the actual drive. Record print orientation, material lot, measured fit and rework.

The camera board, gel blank, adhesive volumes, coating, washers and other purchased-component shapes are **reference envelopes**. Use the real materials/components specified by the BOM.

## Cast the clear gel

Use the two matching mold halves. Smooth and seal the cavity, then make a small cure-compatibility coupon using the same tooling finish and material. The current cavity volume is about **2.86 mL** before process waste; measure the cured result.

Mix [Solaris](https://www.smooth-on.com/products/solaris/) **1A:1B by mass or volume**, without added plasticizer. Its supplier specifies a 24-hour cure at 23°C and a minimum curing temperature of 18°C. Fill the open contact-side cavity, lower the rear mold slowly, and release air/excess through the four fill and four vent openings. Clamp the halves evenly with the M3 tooling holes.

Demold after the documented cure. Reject incomplete flanges, tears, trapped bubbles in the view, or a tacky/inhibited surface. Measure the main thickness and 0.7 mm rear flange. The design has no assumed shrinkage compensation.

## Apply markers and the white contact coating

Use [Psycho Paint](https://www.smooth-on.com/products/psycho-paint/) with [Silc Pig](https://www.smooth-on.com/products/silc-pig/). Mix the paint base **1A:1B by mass**. For the first controlled batch, add black pigment at **1%** and white pigment at **3%** of the combined A+B mass. For example, 5 g A + 5 g B takes 0.10 g black or 0.30 g white pigment.

On the clean, cured gel, use the [marker stencil and 1:1 pattern](assets/prototypes/optical/patterns/o1_marker_pattern.svg) to apply 42 nominal Ø0.6 mm black dots. Then cover them with a continuous white layer, targeting **0.10 mm dry thickness**. The camera sees through clear gel to black dots against the white background. Brush or stipple without solvent; qualify opacity, adhesion, friction and wear on a coupon first.

The supplier's undiluted paint cure is about two hours at room temperature. Follow its current surface preparation and cure instructions. Inspect the actual optical image after coating; the thickness and pigment percentages are process targets, not proven sensing specifications.

## Install mirror, gel, camera and light

1. Cut the PET mirror with the [1:1 mirror pattern](assets/prototypes/optical/patterns/o1_mirror_cut.svg). Bond it to the rigid backing with nominal 0.05 mm 3M 467MP transfer adhesive. Keep the viewing surface flat and clean.
2. Seat the gel's rear flanges on a nominal 0.10 mm [Sil-Poxy](https://www.smooth-on.com/products/sil-poxy/) bond. Qualify Solaris-to-printed-material adhesion first; the supplier specifies 24 hours for full cure.
3. Install both retaining clips with eight M2×6 screws, one 0.5 mm washer per screw and the side-loaded M2 nuts. The model leaves 0.05 mm flange clearance; establish retention from measured parts rather than applying arbitrary preload.
4. Install drive fasteners while access is open. Mount the camera on its four supports, following the 180° orientation in the CAD. Use two M2×8 screws at the rear camera holes.
5. Fit the LED carrier to the front camera holes with **two M2×14 screws and three 0.5 mm washers at each head**. The carrier bears on mounting lands, leaving the autofocus housing/barrel clear. Reuse the two camera nuts underneath.
6. Assemble the checked LED board, snap it under the carrier lips and route its two insulated leads through the provided exit. Check lead soldering and retention before closing the lid with four M2×8 screws.

Use the [component-side LED drawing and wiring guide](optical-electronics.html). Route the CSI ribbon through the lid slot. Establish and photograph the full cable slack on the actual drive; the CAD does not qualify the complete moving harness.

## Retain the thin nail interface

Build **only CH0 and CH1** from the supplied R1 cut sheet, following [the R1 N0 recipe](build-r1.html). Use separate pressure-film islands, opposed bare copper electrodes and insulating backings. Put each 100 kΩ continuity resistor and its solder joints outside the loaded nail.

Keep the nominal 0.30 mm laminate and 0.10 mm mounting film. Measure the installed thickness, notch access and leading-edge behavior. Connect the two cells separately to A0 and A1; the optical gel does not cover the hard nail.

Proceed to [capture setup](optical-electronics.html) and [physical acceptance and comparison](optical-testing.html).
