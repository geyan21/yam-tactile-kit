"""B2 identity check plus the unchanged, strict B1 signal-format decoder."""

import b1_protocol

PROTOCOL = "yam-b2/1"


def decode(frame):
    if not isinstance(frame,dict) or frame.get("protocol") != PROTOCOL:
        raise ValueError("Not a B2 sample; B1 recordings cannot be relabeled as B2")
    # Only the framing identifier differs. Keep the original frame untouched
    # in the recorder; reuse range, status, timing, resistor and fault checks.
    observation = b1_protocol.decode({**frame,"protocol":b1_protocol.PROTOCOL})
    return {**observation,"design_id":"B2","hardware_revision":"B2.1"}


native_vectors = b1_protocol.native_vectors
