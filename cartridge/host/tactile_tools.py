"""
Host-side helpers for the YAM tactile cartridges.

  * taxel_points(q_left, q_right)  -> (2, 128, 3) taxel centres in the i2rt gripper body frame
  * lift(frames, q_left, q_right)  -> (N, 4) [x, y, z, value] tactile points for 3D visuo-tactile
                                      fusion (3D-ViTac style); transform with your arm FK
  * FrameParser                    -> parses the cartridge USB-CDC stream (protocol below)
  * flexitac_subblock(frame, ...)  -> pull our 16x8 pad out of a FlexiTac 32x16 readout frame
                                      (bring-up before the finger PCB exists)

Cartridge stream protocol v1 (little endian, one frame per scan, 200 Hz default):
  0xAA 0x55 | ver u8 = 1 | flags u8 | seq u16 | t_us u32 (MCU clock) | 128 x u16 (12-bit ADC,
  row-major, row 0 = distal) | crc u16 over everything after the 2 header bytes
  CRC = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, xorout 0; check("123456789") = 0x29B1)
  -> 268 bytes / frame. USB iSerial = MCU 96-bit UID (hex), so a udev rule can name the port and the
  host can log which physical cartridge produced each episode.
"""
import json
import os
import struct
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # cartridge/
TAXEL_MAP = os.path.join(ROOT, "out", "taxel_map.json")
PINMAP = os.path.join(ROOT, "out", "fpc_pcb", "pinmap.json")
NR, NC = 16, 8
FRAME_LEN = 2 + 1 + 1 + 2 + 4 + 2 * NR * NC + 2


def load_map(path=TAXEL_MAP):
    return json.load(open(path))


def taxel_points(q_left, q_right, tmap=None):
    """Taxel centres (m) in the gripper body frame for finger openings q (m, per finger, as joint7/8)."""
    tmap = tmap or load_map()
    out = []
    for side, q in (("left", q_left), ("right", q_right)):
        f = tmap["fingers"][side]
        out.append(np.array(f["taxels_q0"]) + q * np.array(f["slide_dir"]))
    return np.stack(out)


def lift(frames, q_left, q_right, threshold=0.0, tmap=None):
    """frames: dict side -> (16, 8) array (normalised pressure). Returns (N, 4) [x, y, z, value]."""
    pts = taxel_points(q_left, q_right, tmap)
    rows = []
    for i, side in enumerate(("left", "right")):
        v = np.asarray(frames[side], float).reshape(-1)
        keep = v > threshold
        rows.append(np.column_stack([pts[i][keep], v[keep]]))
    return np.vstack(rows)


def crc16_ccitt(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class FrameParser:
    """Feed raw bytes; yields dicts with seq, t_us, frame (16x8 uint16)."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        while True:
            i = self.buf.find(b"\xAA\x55")
            if i < 0:
                self.buf = self.buf[-1:]
                return
            if len(self.buf) - i < FRAME_LEN:
                self.buf = self.buf[i:]
                return
            pkt = bytes(self.buf[i:i + FRAME_LEN])
            body, crc = pkt[2:-2], struct.unpack("<H", pkt[-2:])[0]
            if crc16_ccitt(body) != crc:
                self.buf = self.buf[i + 2:]
                continue
            ver, flags, seq, t_us = struct.unpack("<BBHI", body[:8])
            vals = np.frombuffer(body[8:], dtype="<u2").reshape(NR, NC)
            self.buf = self.buf[i + FRAME_LEN:]
            yield dict(ver=ver, flags=flags, seq=seq, t_us=t_us, frame=vals.copy())


def encode_frame(seq, t_us, frame, ver=1, flags=0):
    body = struct.pack("<BBHI", ver, flags, seq, t_us) + np.asarray(frame, "<u2").tobytes()
    return b"\xAA\x55" + body + struct.pack("<H", crc16_ccitt(body))


def rows_readout_order(path=PINMAP):
    """Readout line (tail pin - 1) for ROW00..ROW15. The proximal half of the rows tail is reversed
    by the routing (pins 9..16 carry ROW15..ROW08), so this is [0..7, 15..8]."""
    return json.load(open(path))["rows_readout_order"]


def flexitac_subblock(frame_16x32, row_lines=None, col_lines=range(8), row_offset=0, col_offset=0):
    """FlexiTac 32x16 board frame (16 x 32) -> our (16, 8) block, rows in physical order (0 = distal).
    Assumes tail pin i is wired to readout line offset + i; defaults follow out/fpc_pcb/pinmap.json."""
    if row_lines is None:
        row_lines = rows_readout_order()
    f = np.asarray(frame_16x32)
    return f[np.ix_([row_offset + r for r in row_lines], [col_offset + c for c in col_lines])]


class Baseline:
    """Per-taxel auto-zero: call reset() with the gripper open (no contact) at episode start."""

    def __init__(self, n=20):
        self.n, self.acc, self.base = n, [], None

    def reset(self):
        self.acc, self.base = [], None

    def __call__(self, frame):
        f = np.asarray(frame, float)
        if self.base is None:
            self.acc.append(f)
            if len(self.acc) >= self.n:
                self.base = np.median(self.acc, axis=0)
            return np.zeros_like(f)
        return np.clip(f - self.base, 0, None)


if __name__ == "__main__":
    # round-trip + geometry smoke test
    assert crc16_ccitt(b"123456789") == 0x29B1, "CRC variant"
    order = rows_readout_order()
    assert order[:8] == list(range(8)) and order[8:] == list(range(15, 7, -1)), order
    fake = np.zeros((16, 32)); fake[order[3], 5] = 1.0          # ROW03 lit on line order[3]
    assert flexitac_subblock(fake)[3, 5] == 1.0
    p = FrameParser()
    fr = (np.arange(NR * NC) % 4096).reshape(NR, NC)
    stream = b"\x00\x13" + encode_frame(7, 123456, fr) + encode_frame(8, 128456, fr[::-1])
    got = list(p.feed(stream))
    assert [g["seq"] for g in got] == [7, 8] and np.array_equal(got[0]["frame"], fr)
    pts = taxel_points(0.0, 0.0)
    print("parser ok; frame bytes", FRAME_LEN, "| right r0c0", np.round(pts[1][0] * 1000, 2),
          "mm | left r0c0", np.round(pts[0][0] * 1000, 2), "mm")
    print("lifted points:", lift({"left": np.ones((16, 8)), "right": np.zeros((16, 8))}, 0.01, 0.01, 0.5).shape)
