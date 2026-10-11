# YAM tactile cartridge pipeline. Run from this folder: `make i2rt && make all`.
PY ?= python3
I2RT_ROOT ?= $(CURDIR)/third_party/i2rt
I2RT_COMMIT := 120c3c81400171174604e503943f8d1ebc891058
export I2RT_ROOT

.PHONY: all cad fpc checks sim renders web verify standalone i2rt enpire enpire-src enpire-cad enpire-fpc enpire-checks enpire-sim enpire-renders \
        enpire-tip enpire-tip-cad enpire-tip-fpc enpire-tip-checks enpire-tip-sim enpire-tip-renders

all: cad fpc checks sim renders enpire enpire-tip web

i2rt: $(I2RT_ROOT)/.git
$(I2RT_ROOT)/.git:
	git clone --filter=blob:none https://github.com/i2rt-robotics/i2rt.git $(I2RT_ROOT)
	git -C $(I2RT_ROOT) checkout --quiet $(I2RT_COMMIT)

cad:            # parts, assembly STEP, params.json
	$(PY) cad/yam_tactile_finger.py
fpc: cad        # FPC + PCB DXFs, pinmap.json, taxel_map.json
	$(PY) cad/fpc_pcb_layout.py
checks: fpc     # interference + clearance sweep, measurements.json
	$(PY) cad/check_fit.py
	$(PY) cad/measure.py
sim: fpc        # MuJoCo model with 256 touch sensors + self-test
	$(PY) cad/make_sim_model.py
renders: checks # section views and shaded renders
	$(PY) cad/render_views.py
	$(PY) cad/render_vtk.py
# --- ENPIRE-T: the ENPIRE finger as a tactile cartridge on the same socket (outputs in out/enpire/) ---
enpire-src:     # ENPIRE STLs from Open-ENPIRE-Gripper at a pinned commit, SHA-256 checked (the originals are not committed)
	$(PY) cad/enpire_source.py
enpire-cad: enpire-src
	$(PY) cad/enpire_finger.py --build
enpire-fpc: enpire-cad   # two-sheet laminate flat pattern + DRC, pinmap, taxel_map, finger PCB
	$(PY) cad/enpire_fpc.py
enpire-checks: enpire-fpc   # fit/shape/wall checks vs the YAM and the original ENPIRE (uses the committed v0.2 socket parts)
	$(PY) cad/enpire_check.py
	$(PY) cad/enpire_measure.py
enpire-sim: enpire-fpc  # MuJoCo model with 2 x 302 touch sensors + nail-pinch and cradle-grasp self-tests
	$(PY) cad/enpire_sim.py
enpire-renders: enpire-checks
	$(PY) cad/enpire_render.py
enpire: enpire-cad enpire-fpc enpire-checks enpire-sim enpire-renders
# --- ENPIRE-T Tip: ENPIRE with the stock TPU cradle, sensing on the nail only (outputs in out/enpire_tip/) ---
enpire-tip-cad: enpire-src
	$(PY) cad/enpire_tip.py --build
enpire-tip-fpc: enpire-tip-cad   # nail pad + side-by-side tails: flat pattern, DRC, pinmap, taxel_map, finger PCB
	$(PY) cad/enpire_tip_fpc.py
enpire-tip-checks: enpire-tip-fpc   # fit/shape/wall checks vs the YAM and the original ENPIRE, measurements
	$(PY) cad/enpire_tip_check.py
enpire-tip-sim: enpire-tip-fpc  # MuJoCo model with 2 x 92 touch sensors + pin, rod and flat-plate self-tests
	$(PY) cad/enpire_tip_sim.py
enpire-tip-renders: enpire-tip-checks
	$(PY) cad/enpire_tip_render.py
enpire-tip: enpire-tip-cad enpire-tip-fpc enpire-tip-checks enpire-tip-sim enpire-tip-renders

web: checks sim enpire enpire-tip   # web/data.js, data_enpire.js, data_enpire_tip.js + web/index.html from the outputs above
	$(PY) cad/export_web.py

standalone:     # self-contained copy of the current page for any static host -> build/standalone/
	$(PY) tools/build_standalone.py

verify:         # output consistency (stdlib), host-tool self-test, page check in headless Chromium
	$(PY) tools/check_outputs.py
	$(PY) host/tactile_tools.py
	$(PY) tools/verify_web.py
