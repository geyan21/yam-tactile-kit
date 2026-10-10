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

Stream protocol v2 (any layout; the ENPIRE-T cartridge uses it):
  0xAA 0x55 | ver u8 = 2 | flags u8 | seq u16 | t_us u32 | layout u8 | reserved u8 | n u16 |
  n x u16 (12-bit ADC, taxel order of that layout's taxel_map.json) | crc u16 (same CRC, same span)
  layout 1 = v0.2 flat cartridge (n = 128), layout 2 = ENPIRE-T (n = 302) -> 620 bytes / frame.
  The parser below accepts v1 and v2 frames on the same port.
"""
import json
import os
import struct
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # cartridge/
TAXEL_MAP = os.path.join(ROOT, "out", "taxel_map.json")
PINMAP = os.path.join(ROOT, "out", "fpc_pcb", "pinmap.json")
LAYOUTS = {
    1: dict(name="v0.2 flat cartridge", n=128, taxel_map=TAXEL_MAP, pinmap=PINMAP),
    2: dict(name="ENPIRE-T", n=302, taxel_map=os.path.join(ROOT, "out", "enpire", "taxel_map.json"),
            pinmap=os.path.join(ROOT, "out", "enpire", "fpc_pcb", "pinmap.json")),
}
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
    """Feed raw bytes; yields dicts with ver, seq, t_us and either frame (v1: 16x8 uint16) or
    layout + values (v2: n uint16 in taxel-map order)."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        while True:
            i = self.buf.find(b"\xAA\x55")
            if i < 0:
                self.buf = self.buf[-1:]
                return
            if len(self.buf) - i < 3:
                self.buf = self.buf[i:]
                return
            ver = self.buf[i + 2]
            if ver == 1:
                n_bytes = FRAME_LEN
            elif ver == 2:
                if len(self.buf) - i < 16:
                    self.buf = self.buf[i:]
                    return
                n = struct.unpack("<H", bytes(self.buf[i + 12:i + 14]))[0]
                if n == 0 or n > 4096:
                    self.buf = self.buf[i + 2:]
                    continue
                n_bytes = 16 + 2 * n
            else:
                self.buf = self.buf[i + 2:]
                continue
            if len(self.buf) - i < n_bytes:
                self.buf = self.buf[i:]
                return
            pkt = bytes(self.buf[i:i + n_bytes])
            body, crc = pkt[2:-2], struct.unpack("<H", pkt[-2:])[0]
            if crc16_ccitt(body) != crc:
                self.buf = self.buf[i + 2:]
                continue
            self.buf = self.buf[i + n_bytes:]
            ver, flags, seq, t_us = struct.unpack("<BBHI", body[:8])
            if ver == 1:
                vals = np.frombuffer(body[8:], dtype="<u2").reshape(NR, NC)
                yield dict(ver=ver, flags=flags, seq=seq, t_us=t_us, frame=vals.copy())
            else:
                layout, _, n = struct.unpack("<BBH", body[8:12])
                vals = np.frombuffer(body[12:], dtype="<u2")
                yield dict(ver=ver, flags=flags, seq=seq, t_us=t_us, layout=layout, values=vals.copy())


def encode_frame(seq, t_us, frame, ver=1, flags=0):
    body = struct.pack("<BBHI", ver, flags, seq, t_us) + np.asarray(frame, "<u2").tobytes()
    return b"\xAA\x55" + body + struct.pack("<H", crc16_ccitt(body))


def encode_frame_v2(seq, t_us, values, layout=2, flags=0):
    v = np.asarray(values, "<u2").ravel()
    body = struct.pack("<BBHIBBH", 2, flags, seq, t_us, layout, 0, len(v)) + v.tobytes()
    return b"\xAA\x55" + body + struct.pack("<H", crc16_ccitt(body))


def layout_points(layout, q_left, q_right, surface=True, tmap=None):
    """(2, n, 3) taxel points (m) in the gripper body frame for a v2 layout. ENPIRE-T maps carry
    the sensing-layer point and the contact-surface point; `surface` picks the latter."""
    tmap = tmap or json.load(open(LAYOUTS[layout]["taxel_map"]))
    out = []
    for side, q in (("left", q_left), ("right", q_right)):
        f = tmap["fingers"][side]
        key = "taxels_q0" if "taxels_q0" in f else ("surface_q0" if surface else "sensor_q0")
        out.append(np.array(f[key]) + q * np.array(f["slide_dir"]))
    return np.stack(out)


def layout_lift(values, layout, q_left, q_right, threshold=0.0, tmap=None):
    """values: dict side -> n readings (normalised). Returns (N, 4) [x, y, z, value] contact points."""
    pts = layout_points(layout, q_left, q_right, True, tmap)
    rows = []
    for i, side in enumerate(("left", "right")):
        v = np.asarray(values[side], float).reshape(-1)
        keep = v > threshold
        rows.append(np.column_stack([pts[i][keep], v[keep]]))
    return np.vstack(rows)


def scan_table(layout=2):
    """Firmware table for a v2 layout: (row_line, col_line) per taxel, in taxel-map order. Row and
    column lines are indices into the pin map's scan lists (i.e. the mux channel order)."""
    tm = json.load(open(LAYOUTS[layout]["taxel_map"]))
    pm = json.load(open(LAYOUTS[layout]["pinmap"]))
    rl = {n: k for k, n in enumerate(pm["scan"]["row_lines"])}
    cl = {n: k for k, n in enumerate(pm["scan"]["col_lines"])}
    return [(rl[t["row_net"]], cl[t["col_net"]]) for t in tm["taxels"]]


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
    if os.path.isfile(LAYOUTS[2]["taxel_map"]):
        n = LAYOUTS[2]["n"]
        v = np.arange(n) % 4096
        f2 = encode_frame_v2(9, 1000, v)
        mixed = encode_frame(10, 2000, fr)[:5] + f2 + encode_frame(11, 3000, fr) + f2[:40]      # junk, v2, v1, partial v2
        got = list(FrameParser().feed(mixed))
        assert [g["ver"] for g in got] == [2, 1] and np.array_equal(got[0]["values"], v) and len(f2) == 16 + 2 * n
        tab = scan_table(2)
        assert len(tab) == n and len(set(tab)) == n, "two taxels share a row/column crossing"
        P = layout_points(2, 0.0, 0.0)
        assert P.shape == (2, n, 3) and np.allclose(P[0] * [-1, -1, 1], P[1])
        print(f"v2 ok: ENPIRE-T {n} taxels, {len(f2)} bytes/frame, {max(r for r, _ in tab) + 1} row x "
              f"{max(c for _, c in tab) + 1} column lines; nail tip taxel at", np.round(P[1][-1] * 1000, 2), "mm")
