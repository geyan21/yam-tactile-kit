"""F1 wrist bench capture. Copy all four files together to the selected Pico."""

import gc
import json
from time import sleep_ms
from hardware import Hardware
from scan import Scanner, checked_config

with open("config.json") as stream:
    config = checked_config(json.load(stream))

hardware = Hardware(config)
scanner = Scanner(hardware, config)


def emit(record):
    print(json.dumps(record))


hello = {"kind": "hello", "schema": "yam-f1-raw-stream/1",
         "firmware": "F1.1-development", "sensor_only": True,
         "force_calibration_loaded": False, "fault_check_qualified": False,
         "configuration": config}

frame = 0
try:
    while True:
        # A newly attached recorder can synchronize without resetting or
        # writing commands to the sensor board.
        hello["next_frame"] = frame
        emit(hello)
        scanner.capture_frame(frame, emit)
        frame += 1
        gc.collect()
        sleep_ms(config["pause_between_frames_ms"])
except BaseException as error:
    hardware.park()
    emit({"kind": "error", "frame": frame, "message": str(error),
          "capture_stopped": True})
    raise
