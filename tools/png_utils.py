#!/usr/bin/env python3
"""
PNG encoding utilities for SuperRTP.
Provides 100% deterministic, cross-platform RFC 1950 / RFC 1951 encoding that produces
identical byte output regardless of whether the system Python is linked against
classic zlib, zlib-ng, Apple zlib, or Windows zlib.
"""

import struct
import zlib

def deterministic_zlib_compress(data: bytes) -> bytes:
    """
    Compresses data into an RFC 1950 zlib stream using RFC 1951 uncompressed (stored)
    blocks. This avoids all C-level heuristic differences between zlib implementations,
    guaranteeing bit-for-bit identical outputs everywhere.
    """
    cmf = 0x78
    flg = 0x01  # (0x78 * 256 + 0x01) % 31 == 0
    header = bytes([cmf, flg])
    blocks = []
    chunk_size = 65535
    total = len(data)
    for i in range(0, max(total, 1), chunk_size):
        chunk = data[i:i+chunk_size]
        is_last = 1 if (i + chunk_size >= total) else 0
        b_hdr = bytes([is_last])
        nlen = (~len(chunk)) & 0xffff
        blocks.append(b_hdr + struct.pack('<HH', len(chunk), nlen) + chunk)
    adler = struct.pack('>I', zlib.adler32(data) & 0xffffffff)
    return header + b''.join(blocks) + adler

def make_png_chunk(chunk_type: str, data: bytes) -> bytes:
    """Encodes a standard PNG chunk with 4-byte length, 4-byte type, payload, and CRC32."""
    c_type = chunk_type.encode('ascii')
    crc = zlib.crc32(c_type + data) & 0xffffffff
    return struct.pack('>I', len(data)) + c_type + data + struct.pack('>I', crc)
