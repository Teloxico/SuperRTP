"""
WOLF RPG Editor v3 Map (.mps) parser, serializer, and helper utilities.
Based on WOLF RPG Editor v3.x binary file specifications.
"""

from __future__ import annotations

import ctypes
import os
import struct
from typing import Any, Dict, List, Optional, Tuple

_LZ4_LIB = None

def _get_lz4():
    global _LZ4_LIB
    if _LZ4_LIB is None:
        lib = ctypes.CDLL("liblz4.so.1")
        lib.LZ4_decompress_safe.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.LZ4_decompress_safe.restype = ctypes.c_int
        lib.LZ4_compress_default.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.LZ4_compress_default.restype = ctypes.c_int
        _LZ4_LIB = lib
    return _LZ4_LIB


def decompress_mps(raw: bytes) -> Tuple[bytes, bytes]:
    """Decompress .mps file. Returns (header_25_bytes, decompressed_body)."""
    header = raw[:25]
    dec_size = struct.unpack("<I", raw[25:29])[0]
    enc_size = struct.unpack("<I", raw[29:33])[0]
    lz4 = _get_lz4()
    out_buf = ctypes.create_string_buffer(dec_size)
    res = lz4.LZ4_decompress_safe(raw[33:33 + enc_size], out_buf, enc_size, dec_size)
    if res < 0:
        raise ValueError(f"LZ4 decompression failed with error {res}")
    return header, bytes(out_buf)


def compress_mps(header: bytes, body: bytes) -> bytes:
    """Compress map body using LZ4 and prepend header."""
    dec_size = len(body)
    max_enc = dec_size * 2 + 100
    dst = ctypes.create_string_buffer(max_enc)
    lz4 = _get_lz4()
    enc_size = lz4.LZ4_compress_default(bytes(body), dst, dec_size, max_enc)
    if enc_size <= 0:
        raise ValueError(f"LZ4 compression failed with error {enc_size}")
    return header[:25] + struct.pack("<II", dec_size, enc_size) + dst.raw[:enc_size]


class Coder:
    """Binary reader/writer for WOLF data files."""

    def __init__(self, data: bytes = b""):
        self.data = bytearray(data)
        self.p = 0

    def read_bytes(self, n: int) -> bytes:
        res = bytes(self.data[self.p : self.p + n])
        self.p += n
        return res

    def read_byte(self) -> int:
        res = self.data[self.p]
        self.p += 1
        return res

    def read_int(self) -> int:
        res = struct.unpack("<I", self.data[self.p : self.p + 4])[0]
        self.p += 4
        return res

    def read_string(self) -> bytes:
        l = self.read_int()
        s = bytes(self.data[self.p : self.p + l])
        self.p += l
        return s

    def write_byte(self, b: int) -> None:
        self.data.append(b & 0xFF)

    def write_bytes(self, bs: bytes) -> None:
        self.data.extend(bs)

    def write_int(self, v: int) -> None:
        self.data.extend(struct.pack("<I", v & 0xFFFFFFFF))

    def write_string(self, s: bytes) -> None:
        self.write_int(len(s))
        self.write_bytes(s)


def parse_route_cmd(c: Coder) -> Tuple[int, List[int]]:
    cid = c.read_byte()
    ac = c.read_byte()
    args = [c.read_int() for _ in range(ac)]
    term = c.read_bytes(2)
    if term != b"\x01\x00":
        raise ValueError(f"Invalid route command terminator: {term!r}")
    return (cid, args)


def dump_route_cmd(c: Coder, rcmd: Tuple[int, List[int]]) -> None:
    cid, args = rcmd
    c.write_byte(cid)
    c.write_byte(len(args))
    for a in args:
        c.write_int(a)
    c.write_bytes(b"\x01\x00")


def parse_page(c: Coder, version: int = 0x67) -> Dict[str, Any]:
    unk1 = c.read_int()
    gname = c.read_string()
    gdir = c.read_byte()
    gframe = c.read_byte()
    gopac = c.read_byte()
    grm = c.read_byte()
    conds = c.read_bytes(37)
    move = c.read_bytes(4)
    flags = c.read_byte()
    rflags = c.read_byte()
    rcnt = c.read_int()
    routes = [parse_route_cmd(c) for _ in range(rcnt)]
    cmd_cnt = c.read_int()
    cmds = []
    for _ in range(cmd_cnt):
        argc_raw = c.read_byte()
        argc = argc_raw - 1
        cid = c.read_int()
        args = [c.read_int() for _ in range(argc)]
        indent = c.read_byte()
        strc = c.read_byte()
        str_args = [c.read_string() for _ in range(strc)]
        term = c.read_byte()
        route_term = None
        if term == 1:
            u = [c.read_byte() for _ in range(5)]
            f = c.read_byte()
            rc = c.read_int()
            r_list = [parse_route_cmd(c) for _ in range(rc)]
            route_term = (u, f, r_list)
        v35 = b""
        if version >= 0x67:
            v35_sz = c.read_byte()
            if v35_sz > 0:
                v35 = c.read_bytes(v35_sz)
        cmds.append((cid, args, indent, str_args, term, route_term, v35))
    features = c.read_int()
    shadow = c.read_byte()
    col_w = c.read_byte()
    col_h = c.read_byte()
    ptransfer = None
    if features > 3:
        ptransfer = c.read_byte()
    pterm = c.read_byte()
    if pterm != 0x7A:
        raise ValueError(f"Expected page terminator 0x7A, got {hex(pterm)} at offset {c.p}")
    return {
        "unk1": unk1,
        "gname": gname,
        "gdir": gdir,
        "gframe": gframe,
        "gopac": gopac,
        "grm": grm,
        "conds": conds,
        "move": move,
        "flags": flags,
        "rflags": rflags,
        "routes": routes,
        "cmds": cmds,
        "features": features,
        "shadow": shadow,
        "col_w": col_w,
        "col_h": col_h,
        "ptransfer": ptransfer,
    }


def dump_page(c: Coder, pg: Dict[str, Any], version: int = 0x67) -> None:
    c.write_int(pg["unk1"])
    c.write_string(pg["gname"])
    c.write_byte(pg["gdir"])
    c.write_byte(pg["gframe"])
    c.write_byte(pg["gopac"])
    c.write_byte(pg["grm"])
    c.write_bytes(pg["conds"])
    c.write_bytes(pg["move"])
    c.write_byte(pg["flags"])
    c.write_byte(pg["rflags"])
    c.write_int(len(pg["routes"]))
    for r in pg["routes"]:
        dump_route_cmd(c, r)
    c.write_int(len(pg["cmds"]))
    for cmd in pg["cmds"]:
        cid, args, indent, str_args, term, route_term, v35 = cmd
        c.write_byte(len(args) + 1)
        c.write_int(cid)
        for a in args:
            c.write_int(a)
        c.write_byte(indent)
        c.write_byte(len(str_args))
        for s in str_args:
            c.write_string(s)
        c.write_byte(term)
        if term == 1:
            u, f, r_list = route_term
            for ub in u:
                c.write_byte(ub)
            c.write_byte(f)
            c.write_int(len(r_list))
            for r in r_list:
                dump_route_cmd(c, r)
        if version >= 0x67:
            c.write_byte(len(v35))
            if len(v35) > 0:
                c.write_bytes(v35)
    c.write_int(pg["features"])
    c.write_byte(pg["shadow"])
    c.write_byte(pg["col_w"])
    c.write_byte(pg["col_h"])
    if pg["features"] > 3:
        c.write_byte(pg["ptransfer"] if pg["ptransfer"] is not None else 0)
    c.write_byte(0x7A)


def parse_mps_body(data: bytes, version: int = 0x67) -> Dict[str, Any]:
    c = Coder(data)
    name = c.read_string()
    tileset_id = c.read_int()
    w = c.read_int()
    h = c.read_int()
    ev_cnt = c.read_int()
    unk4 = c.read_int()
    lcnt = c.read_int()
    tiles = c.read_bytes(w * h * lcnt * 4)
    events = []
    for i in range(ev_cnt):
        ind = c.read_byte()
        if ind != 0x6F:
            raise ValueError(f"Expected event indicator 0x6F, got {hex(ind)} at offset {c.p}")
        m1 = c.read_bytes(4)
        eid = c.read_int()
        ename = c.read_string()
        x = c.read_int()
        y = c.read_int()
        pcnt = c.read_int()
        m2 = c.read_bytes(4)
        pages = []
        while True:
            p_ind = c.read_byte()
            if p_ind == 0x79:
                pages.append(parse_page(c, version))
            elif p_ind == 0x70:
                break
            else:
                raise ValueError(f"Unexpected page indicator {hex(p_ind)} at offset {c.p}")
        events.append({"id": eid, "name": ename, "x": x, "y": y, "pages": pages, "m1": m1, "m2": m2})
    term = c.read_byte()
    if term != 0x66:
        raise ValueError(f"Expected map terminator 0x66, got {hex(term)} at offset {c.p}")
    if c.p != len(data):
        raise ValueError(f"Trailing bytes after map terminator: {len(data) - c.p} bytes")
    return {
        "name": name,
        "tileset_id": tileset_id,
        "width": w,
        "height": h,
        "unk4": unk4,
        "lcnt": lcnt,
        "tiles": tiles,
        "events": events,
    }


def dump_mps_body(map_dict: Dict[str, Any], version: int = 0x67) -> bytes:
    out = Coder()
    out.write_string(map_dict["name"])
    out.write_int(map_dict["tileset_id"])
    out.write_int(map_dict["width"])
    out.write_int(map_dict["height"])
    out.write_int(len(map_dict["events"]))
    out.write_int(map_dict["unk4"])
    out.write_int(map_dict["lcnt"])
    out.write_bytes(map_dict["tiles"])
    for ev in map_dict["events"]:
        out.write_byte(0x6F)
        out.write_bytes(ev.get("m1", b"\x39\x30\x00\x00"))
        out.write_int(ev["id"])
        out.write_string(ev["name"])
        out.write_int(ev["x"])
        out.write_int(ev["y"])
        out.write_int(len(ev["pages"]))
        out.write_bytes(ev.get("m2", b"\x00\x00\x00\x00"))
        for pg in ev["pages"]:
            out.write_byte(0x79)
            dump_page(out, pg, version)
        out.write_byte(0x70)
    out.write_byte(0x66)
    return bytes(out.data)
