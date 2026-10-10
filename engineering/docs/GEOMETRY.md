# Geometry, interfaces, and provenance

The user's working finger is Wenli Xiao's [MakerWorld ENPIRE finger](https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm#profileId-3349177), linked to [NVIDIA ENPIRE](https://research.nvidia.com/labs/gear/enpire/).

The original public metadata identifies PETG for the hard part and TPU 85A or 90A for the soft part. Its listed profile uses a 0.4 mm nozzle, 0.2 mm layers, two walls, and 100% infill. Preserve that as the control recipe; changing infill or hardness is an experimental variable.

## Geometry used here

The anonymous metadata lists original hard STL, soft STL, and STEP files, but did not supply an anonymous download URL. The analysis therefore uses the YAM component STLs from [Open-ENPIRE-Gripper](https://github.com/pgeedh/Open-ENPIRE-Gripper/tree/72cc833bfe1521132318db6a2724e7e9bbb8cd6e/grippers-stl/enpire_i2rt_yam_stl).

Their byte sizes match the original listing exactly: 487,484 and 179,484 bytes. This is corroboration, not proof of byte identity. The official NVIDIA simulation mesh also has a matching overall envelope after an apparent scale conversion; it is not used as manufacturing CAD.

| Measured feature | Value | Consequence |
|---|---:|---|
| TPU width | 15.00 mm | A 20 mm board cannot directly replace the insert |
| TPU native-Y span | 81.04 mm | Surface length must be derived from the curved profile |
| Hard nail beyond TPU | 22.84 mm | TPU sensing alone misses hard leading-nail contacts |
| Nail contact-plane area | 326.21 mm² | Shape is forked, not rectangular |
| Minimum sampled nail wall | 1.35 mm | R1 adds a removable laminate; no recess is cut |
| Mount-bore center spacing | 21.00 mm | Verify with the supplied fit gauge |
| Sampled TPU section mismatch | under 10⁻¹² mm | Static profile is an extrusion across its width |

The nail-wall result samples the first solid interval normal to the contact surface on a 0.3 mm grid, inset 0.1 mm from the edge. It is not a structural strength result or a guarantee of the unsampled edge minimum.

Native axes are retained: X spans the insert width, −Y points distally, and roughly −Z points outward from the contact face. The nail has its own slightly tilted local U/V plane, stored in `contact_report.json`. Each saddle has a CSV mapping surface arc length to native Y/Z.

## Digital checks and physical checks

Generated molds and witnesses pass solid validity, STEP re-import volume, and watertight STL checks. Saddle profiles are trimmed against the exact sampled mesh section plus clearance; they have no overlap with that section. These are static geometry checks.

Check the actual finger, cast shrinkage, adhesive thickness, mold surface quality, lead clearance, and compliant motion before loading. The molding witness is not a replacement TPU skeleton. The mounting gauge is not a load-bearing force adapter.

## Attribution and source hashes

Original geometry: Wenli Xiao / ENPIRE. The original metadata records license code `BY`; retain its attribution and consult the original model's license when redistributing modified original geometry. The community repository's license does not replace the original creator's terms.

Hard SHA-256: `b59f7e26b280cd31e73f2efeb19d02583ff504edd83d70e6e508f0ce976856df`

Soft SHA-256: `6dc8c8ae8ebe5f4981e4bd097b95b36c9c98cac23020d237aed8418db9c0bbdc`

The kit supplies new interface tooling and measurements. Source downloads and raw metadata remain outside the published release. Obtain the original STEP through the MakerWorld page when available and repeat the fit check against it.
