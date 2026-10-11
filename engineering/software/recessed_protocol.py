"""B3 gain-5 decoder with retained signed-data, status and nail checks."""

import b1_protocol

PROTOCOL = "yam-b3/1"
SETTINGS = {"gain_sel": 5, "resolution": 1, "dig_filt": 2, "osr": 2,
            "hallconf": 12, "temperature_compensation": False}
LSB_UT = (0.501, 0.501, 0.807)


def decode(frame):
    if not isinstance(frame, dict) or frame.get("protocol") != PROTOCOL:
        raise ValueError("Not a B3 sample")
    settings = frame.get("settings")
    if settings != SETTINGS or any(type(settings[key]) is not type(value)
                                   for key, value in SETTINGS.items()):
        raise ValueError("B3 requires the recorded gain-5 configuration")
    # RES=1, TCMP off has the same signed format and raw rail limits as B1.
    # Reuse its frozen validation, then discard its gain-7 field conversion.
    # The untouched gain-5 frame remains the authoritative raw recording.
    observation = b1_protocol.decode({**frame, "protocol": b1_protocol.PROTOCOL,
                                      "settings": b1_protocol.SETTINGS})
    observation["magnetic_local_ut"] = [
        None if validated is None else [value * lsb for value, lsb
                                        in zip(sensor["raw_xyz"], LSB_UT)]
        for sensor, validated in zip(frame["sensors"], observation["magnetic_local_ut"])
    ]
    if frame["nail_cells"] is not True:
        observation["flags"].append("nail_cells_disabled")
        observation["valid"] = False
    return {**observation, "design_id": "RECESSED", "hardware_revision": "B3.1",
            "settings": dict(SETTINGS), "lsb_ut": list(LSB_UT)}


native_vectors = b1_protocol.native_vectors
