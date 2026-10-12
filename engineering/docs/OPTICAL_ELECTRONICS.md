# O1 wiring, optical setup and raw capture

O1 uses **one Camera Module 3 Wide**, **four blue LEDs**, and **two resistive N0 nail cells**. The camera observes the clear gel through the fixed mirror. The ADS1115 reads the two nail cells; it does not measure the gel.

![O1 exact sensor and wiring map](assets/prototypes/optical/visuals/o1_wiring.svg)

## Assemble the light ring

Order the [checked two-layer PCB fabrication packet](assets/prototypes/optical/electronics/led/o1_blue_ring_fabrication.zip). The ring is 16 × 16 × 0.8 mm with an Ø8 mm nonplated lens hole.

![Actual component-side LED board](assets/prototypes/optical/visuals/o1_led_assembly.svg)

Fit four **Kingbright APT2012QBC/D** LEDs and four **220 Ω, 1%, 1206, ≥0.25 W** resistors. On this component-side drawing, all LED **pin 1/cathode ends are left**, and all pin 2/anode ends are right. Each LED has its own resistor branch. J1 pin 1, the left square land, is +5 V; J1 pin 2 is GND.

The nominal estimate at 5 V and the datasheet's typical 3.3 V forward voltage is about 7.7 mA per branch. That is a circuit estimate; measure actual current, brightness, uniformity and temperature. The [Kingbright data sheet](https://www.kingbrightusa.com/images/catalog/SPEC/APT2012QBC-D.pdf), native PCB, embedded lands and pin/net CSV are included or linked with the board.

## Pi and nail connections

Use a **Raspberry Pi 4 Model B**, its suitable USB-C supply, and the 15-pin camera ribbon. In the table, numbers are **physical GPIO-header pins**.

| Pi connection | Connect to |
|---|---|
| Pin 1, 3.3 V | ADS1115 VDD, both nail excitation leads, A2 supply monitor |
| Pin 3, GPIO2/SDA | ADS1115 SDA |
| Pin 5, GPIO3/SCL | ADS1115 SCL |
| Pin 6, GND | ADS1115 GND and ADDR, LED J1 pin 2, both nail pulldowns, unused A3 |
| Pin 2, 5 V | LED J1 pin 1 |
| CSI camera port | Camera Module 3 Wide ribbon |

Use **Adafruit ADS1115 #1085**, powered at 3.3 V, with ADDR grounded for address **0x48**. Leave ALERT/RDY unconnected. Connect the left nail node to **A0**, and the right nail node to **A1**. Each node needs its own **10 kΩ pulldown to GND**. Each nail has its own **100 kΩ parallel continuity resistor at the cell**.

The recorder checks single-shot mux/gain/rate readback and conversion completion. At ±4.096 V full scale the nominal LSB is 125 µV. The chip's 860 conversions/s setting is not the complete camera/nail frame rate. Follow the [TI input/supply limits](https://www.ti.com/lit/ds/symlink/ads1115.pdf); no analog or I²C input is connected to the 5 V lighting rail.

The host and ADC are external bench components. Mount and insulate their wiring, secure cable exits, and keep the two analog nodes separate. The continuity resistor checks the lead path; it does not diagnose every possible pressure-film failure.

## Establish the optical reference

On Raspberry Pi OS, install/use the official Picamera2 package and enable the Pi's I²C interface. Run these commands from the complete repository. Camera hardware is required; the workstation's CAD tests do not exercise it.

The initial camera file requests **2304 × 1296 at 10 fps**, fixed exposure/gain/color gains, and manual focus. These are starting settings for stationary bench tests. Inspect the entire gel image and adjust focus/exposure before freezing a reference.

```sh
/usr/bin/python3 engineering/software/optical_capture.py \
  --mode setup --camera-config engineering/templates/optical_camera.json \
  --geometry engineering/prototypes/optical/optical_manifest.json \
  --specimen O1-01 --device-id PI4-O1-01 --session setup-01 \
  --condition free-space --duration 3 --output build/o1/setup-01
```

View a saved image and choose an ROI containing all 42 painted dots. The four ROI numbers below are measured image pixels, not supplied calibration:

```sh
/usr/bin/python3 engineering/software/optical_reference.py \
  --capture build/o1/setup-01 --frame FRAME_NUMBER \
  --roi X Y WIDTH HEIGHT --threshold 80 \
  --output build/o1/reference
```

Inspect `markers.svg`: all numbered components must be the painted dots, with adequate focus and separation. If setup fails, correct the physical image or explicitly record new threshold/area settings and rerun. The generated `camera.json` crops saved frames to the selected ROI while preserving the camera controls.

No fluorescent side paint or yellow filter is used in this selected baseline. The camera's Picamera2 `RGB888` array is **B,G,R** in memory; the recorder correctly saves its blue channel and converts the color copy to RGB.

## Record and inspect actual trials

```sh
/usr/bin/python3 engineering/software/optical_capture.py \
  --camera-config build/o1/reference/camera.json \
  --geometry engineering/prototypes/optical/optical_manifest.json \
  --specimen O1-01 --device-id PI4-O1-01 --session train-01 \
  --condition gel-distal-0p2N-01 --duration 15 --output build/o1/captures/hold-001
/usr/bin/python3 engineering/software/optical_process.py \
  --capture build/o1/captures/hold-001 \
  --reference build/o1/reference/reference.json \
  --output build/o1/observations/hold-001.jsonl
```

Each capture saves lossless blue PGM frames, gzip-compressed color PPM frames, camera metadata, raw ADC counts, timing, hashes and a completion receipt. Budget storage from the first actual capture. Keep failed or interrupted directories.

Processing rechecks the source images and metadata. Missing dots, ambiguous assignments, saturated images, changed crop/focus/exposure, dropped frames, nail faults or excessive capture skew produce **unavailable** readings. The observations are pixel motion, log marker-area change and apparent nail conductance. Follow [the physical test page](optical-testing.html) to fit and evaluate force/contact; no model is preloaded.
