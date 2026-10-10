# YAM tactile cartridge pipeline. Run from this folder: `make i2rt && make all`.
PY ?= python3
I2RT_ROOT ?= $(CURDIR)/third_party/i2rt
I2RT_COMMIT := 120c3c81400171174604e503943f8d1ebc891058
export I2RT_ROOT

.PHONY: all cad fpc checks sim renders web verify standalone i2rt

all: cad fpc checks sim renders web

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
web: checks sim # web/data.js + web/index.html from the outputs above
	$(PY) cad/export_web.py

standalone:     # self-contained copy of the current page for any static host -> build/standalone/
	$(PY) tools/build_standalone.py

verify:         # output consistency (stdlib), host-tool self-test, page check in headless Chromium
	$(PY) tools/check_outputs.py
	$(PY) host/tactile_tools.py
	$(PY) tools/verify_web.py
