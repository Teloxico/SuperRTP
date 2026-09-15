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

def create_rgba_png(width: int, height: int, rgba_bytes: bytes) -> bytes:
    """
    Encodes 32-bit RGBA pixels into standard 32-bit truecolor PNG (Color Type 6, bit depth 8)
    using deterministic RFC 1951 stored blocks.
    Supports non-trivial alpha (e.g. A=0, A=128, A=255).
    """
    expected_len = width * height * 4
    if len(rgba_bytes) != expected_len:
        raise ValueError(f"RGBA buffer size mismatch: expected {expected_len}, got {len(rgba_bytes)}")

    png_sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr_chunk = make_png_chunk('IHDR', ihdr_data)

    raw_data = bytearray()
    row_bytes = width * 4
    for y in range(height):
        raw_data.append(0)  # Filter type 0 (None)
        start = y * row_bytes
        raw_data.extend(rgba_bytes[start:start + row_bytes])

    compressed_idat = deterministic_zlib_compress(bytes(raw_data))
    idat_chunk = make_png_chunk('IDAT', compressed_idat)
    iend_chunk = make_png_chunk('IEND', b'')

    return png_sig + ihdr_chunk + idat_chunk + iend_chunk

def decode_png_rgb(filepath):
    """
    Decodes a standard 24-bit PNG file into width, height, and a 2D list of (R, G, B) tuples,
    implementing standard PNG unfiltering (None, Sub, Up, Average, Paeth) per RFC 2083.
    """
    with open(filepath, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {filepath}")

    w, h, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    bpp = 4 if color_type == 6 else 3
    pos = 8
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8]
        if ctype == b"IDAT":
            idat.extend(data[pos+8:pos+8+length])
        pos += 12 + length

    raw = bytearray(zlib.decompress(bytes(idat)))
    stride = 1 + w * bpp
    recon = bytearray(w * h * bpp)
    prior = bytearray(w * bpp)

    for y in range(h):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(w * bpp)

        if filter_type == 0:  # None
            line[:] = filt
        elif filter_type == 1:  # Sub
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:  # Up
            for x in range(w * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:  # Average
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:  # Paeth
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * w * bpp : (y + 1) * w * bpp] = line

    pixels = []
    for y in range(h):
        row = [(recon[y*w*bpp + x*bpp], recon[y*w*bpp + x*bpp + 1], recon[y*w*bpp + x*bpp + 2]) for x in range(w)]
        pixels.append(row)
    return w, h, pixels

def decode_png_rgba(filepath):
    """
    Decodes a standard 32-bit RGBA (or 24-bit RGB) PNG file into width, height, and a 2D list of (R, G, B, A) tuples,
    implementing standard PNG unfiltering (None, Sub, Up, Average, Paeth) per RFC 2083.
    """
    with open(filepath, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {filepath}")

    w, h, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    if color_type not in (2, 6):
        raise ValueError(f"decode_png_rgba requires truecolor PNG (color type 2 or 6), got {color_type}")
    bpp = 4 if color_type == 6 else 3
    pos = 8
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8]
        if ctype == b"IDAT":
            idat.extend(data[pos+8:pos+8+length])
        pos += 12 + length

    raw = bytearray(zlib.decompress(bytes(idat)))
    stride = 1 + w * bpp
    recon = bytearray(w * h * bpp)
    prior = bytearray(w * bpp)

    for y in range(h):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(w * bpp)

        if filter_type == 0:
            line[:] = filt
        elif filter_type == 1:
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:
            for x in range(w * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * w * bpp : (y + 1) * w * bpp] = line

    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            idx = (y * w + x) * bpp
            r = recon[idx]
            g = recon[idx + 1]
            b = recon[idx + 2]
            a = recon[idx + 3] if bpp == 4 else 255
            row.append((r, g, b, a))
        pixels.append(row)
    return w, h, pixels

