#!/usr/bin/env python3
"""
PNG encoding and decoding for SuperRTP (standard library only).

Encoding
--------
All encoders emit byte-for-byte reproducible files: scanlines use filter type 0
and IDAT is an RFC 1950 zlib stream made of RFC 1951 *stored* (uncompressed)
blocks. Stored blocks sidestep every heuristic difference between zlib builds
(classic zlib, zlib-ng, Apple, Windows), so the same pixels always produce the
same bytes on every platform. Generated target packs and canonical assets are
hash-bound in committed evidence, so these encoders must never change output.

Decoding
--------
`read_png` parses and CRC-checks every chunk, validates IHDR, inflates IDAT and
reverses all five PNG scanline filters. Only the subset SuperRTP produces or
captures is supported: 8-bit depth, non-interlaced, color types 2 (RGB),
3 (indexed) and 6 (RGBA). Anything else raises `PngFormatError` rather than
being decoded incorrectly.

`tools/generate_fixture_graphics.py` is hash-frozen by the fixture manifests and
imports `deterministic_zlib_compress` and `make_png_chunk` from this module;
those names and their behavior are part of this module's stable contract.
"""

import struct
import zlib
from dataclasses import dataclass, field

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

COLOR_TYPE_RGB = 2
COLOR_TYPE_INDEXED = 3
COLOR_TYPE_RGBA = 6
_CHANNELS = {COLOR_TYPE_RGB: 3, COLOR_TYPE_INDEXED: 1, COLOR_TYPE_RGBA: 4}

# Largest payload a single RFC 1951 stored block can carry.
_STORED_BLOCK_MAX = 65535


class PngFormatError(ValueError):
    """Raised for malformed PNG data or PNG features outside the supported subset."""


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def deterministic_zlib_compress(data: bytes) -> bytes:
    """
    Wraps `data` in an RFC 1950 zlib stream built from RFC 1951 stored blocks.

    The output depends only on the input bytes, never on the zlib library in use.
    """
    cmf = 0x78
    flg = 0x01  # (0x78 * 256 + 0x01) % 31 == 0, as RFC 1950 requires
    blocks = []
    total = len(data)
    for i in range(0, max(total, 1), _STORED_BLOCK_MAX):
        chunk = data[i:i + _STORED_BLOCK_MAX]
        is_last = 1 if (i + _STORED_BLOCK_MAX >= total) else 0
        nlen = (~len(chunk)) & 0xFFFF
        blocks.append(bytes([is_last]) + struct.pack("<HH", len(chunk), nlen) + chunk)
    adler = struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    return bytes([cmf, flg]) + b"".join(blocks) + adler


def make_png_chunk(chunk_type: str, data: bytes) -> bytes:
    """Encodes one PNG chunk: 4-byte length, 4-byte type, payload, CRC-32."""
    c_type = chunk_type.encode("ascii")
    crc = zlib.crc32(c_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + c_type + data + struct.pack(">I", crc)


def _filter_none_scanlines(pixel_bytes: bytes, row_bytes: int, height: int) -> bytes:
    """Prefixes every scanline with filter type 0 (None)."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        start = y * row_bytes
        raw.extend(pixel_bytes[start:start + row_bytes])
    return bytes(raw)


def create_rgba_png(width: int, height: int, rgba_bytes: bytes) -> bytes:
    """
    Encodes 8-bit RGBA pixels as a truecolor PNG (color type 6) without PLTE or tRNS.

    Alpha is stored as given (0..255, not premultiplied).
    """
    expected_len = width * height * 4
    if len(rgba_bytes) != expected_len:
        raise ValueError(f"RGBA buffer size mismatch: expected {expected_len}, got {len(rgba_bytes)}")

    ihdr = make_png_chunk("IHDR", struct.pack(">IIBBBBB", width, height, 8, COLOR_TYPE_RGBA, 0, 0, 0))
    idat = make_png_chunk("IDAT", deterministic_zlib_compress(_filter_none_scanlines(rgba_bytes, width * 4, height)))
    return PNG_SIGNATURE + ihdr + idat + make_png_chunk("IEND", b"")


def create_indexed_png(width: int, height: int, palette, pixel_indices, has_trns: bool = True) -> bytes:
    """
    Encodes an 8-bit indexed PNG (color type 3).

    `palette` is a sequence of (r, g, b) tuples (at most 256). When `has_trns` is set,
    a one-entry tRNS chunk marks palette index 0 fully transparent, which mirrors the
    RPG Maker 2000/2003 convention that index 0 is the transparent color.
    """
    if len(palette) > 256:
        raise ValueError(f"Palette exceeds 256 entries: {len(palette)}")
    if len(pixel_indices) != width * height:
        raise ValueError(f"Index buffer size mismatch: expected {width * height}, got {len(pixel_indices)}")

    ihdr = make_png_chunk("IHDR", struct.pack(">IIBBBBB", width, height, 8, COLOR_TYPE_INDEXED, 0, 0, 0))
    plte = make_png_chunk("PLTE", bytes(channel for rgb in palette for channel in rgb))
    trns = make_png_chunk("tRNS", b"\x00") if has_trns else b""
    idat = make_png_chunk("IDAT", deterministic_zlib_compress(_filter_none_scanlines(bytes(pixel_indices), width, height)))
    return PNG_SIGNATURE + ihdr + plte + trns + idat + make_png_chunk("IEND", b"")


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

@dataclass
class PngImage:
    """A decoded PNG. `pixels` holds unfiltered samples, `channels` bytes per pixel, row-major."""
    width: int
    height: int
    bit_depth: int
    color_type: int
    interlace: int
    chunks: list = field(repr=False)          # [(type_str, data_bytes), ...] in file order
    pixels: bytes = field(repr=False)
    palette: list = field(default_factory=list, repr=False)  # [(r, g, b), ...] for color type 3
    trns: bytes = field(default=b"", repr=False)

    @property
    def channels(self) -> int:
        return _CHANNELS[self.color_type]

    @property
    def chunk_types(self) -> list:
        return [ctype for ctype, _ in self.chunks]

    def rgba_bytes(self) -> bytes:
        """Returns the image as tightly packed 8-bit RGBA, expanding RGB and palette data."""
        if self.color_type == COLOR_TYPE_RGBA:
            return self.pixels
        out = bytearray(self.width * self.height * 4)
        if self.color_type == COLOR_TYPE_RGB:
            out[0::4] = self.pixels[0::3]
            out[1::4] = self.pixels[1::3]
            out[2::4] = self.pixels[2::3]
            out[3::4] = b"\xff" * (self.width * self.height)
            return bytes(out)
        lut = [(r, g, b, self.trns[i] if i < len(self.trns) else 255) for i, (r, g, b) in enumerate(self.palette)]
        for i, index in enumerate(self.pixels):
            if index >= len(lut):
                raise PngFormatError(f"Palette index {index} out of range ({len(lut)} entries)")
            out[i * 4:i * 4 + 4] = bytes(lut[index])
        return bytes(out)


def parse_png_chunks(data: bytes) -> list:
    """Splits PNG bytes into [(type, payload)], verifying the signature and every CRC."""
    if not data.startswith(PNG_SIGNATURE):
        raise PngFormatError("Invalid PNG: missing or incorrect PNG signature")

    chunks = []
    offset = len(PNG_SIGNATURE)
    data_len = len(data)
    while offset < data_len:
        if offset + 8 > data_len:
            raise PngFormatError("Corrupt PNG: truncated chunk header")
        length, raw_type = struct.unpack(">I4s", data[offset:offset + 8])
        chunk_type = raw_type.decode("ascii", errors="replace")
        offset += 8
        if offset + length + 4 > data_len:
            raise PngFormatError(f"Corrupt PNG: chunk {chunk_type} extends past EOF")
        payload = data[offset:offset + length]
        offset += length
        (crc,) = struct.unpack(">I", data[offset:offset + 4])
        offset += 4
        expected_crc = zlib.crc32(raw_type + payload) & 0xFFFFFFFF
        if crc != expected_crc:
            raise PngFormatError(f"CRC mismatch in {chunk_type} chunk: expected {expected_crc}, got {crc}")
        chunks.append((chunk_type, payload))
    return chunks


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytes:
    """Reverses PNG scanline filtering (RFC 2083 section 6) and returns the packed samples."""
    stride = width * bpp
    if len(raw) != height * (stride + 1):
        raise PngFormatError(f"Decompressed IDAT size mismatch: expected {height * (stride + 1)}, got {len(raw)}")

    out = bytearray(height * stride)
    prior = bytes(stride)
    pos = 0
    for y in range(height):
        filter_type = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += stride + 1

        if filter_type == 0:  # None
            pass
        elif filter_type == 1:  # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prior))
        elif filter_type == 3:  # Average
            for x in range(bpp):
                line[x] = (line[x] + (prior[x] >> 1)) & 0xFF
            for x in range(bpp, stride):
                line[x] = (line[x] + ((line[x - bpp] + prior[x]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(bpp):
                line[x] = (line[x] + prior[x]) & 0xFF  # a = c = 0, so the predictor is b
            for x in range(bpp, stride):
                a = line[x - bpp]
                b = prior[x]
                c = prior[x - bpp]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        else:
            raise PngFormatError(f"Unknown PNG filter type {filter_type}")

        out[y * stride:(y + 1) * stride] = line
        prior = line
    return bytes(out)


def read_png(source) -> PngImage:
    """
    Decodes a PNG from a file path or raw bytes into a `PngImage`.

    Raises `PngFormatError` for corrupt data or unsupported features.
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        with open(source, "rb") as f:
            data = f.read()

    chunks = parse_png_chunks(data)
    if not chunks or chunks[0][0] != "IHDR" or len(chunks[0][1]) != 13:
        raise PngFormatError("PNG must start with a 13-byte IHDR chunk")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunks[0][1])

    if compression != 0 or filter_method != 0:
        raise PngFormatError("Unsupported compression/filter method")
    if interlace != 0:
        raise PngFormatError("Interlaced PNGs are not supported")
    if bit_depth != 8:
        raise PngFormatError(f"Unsupported bit depth {bit_depth}: only 8-bit PNGs are supported")
    if color_type not in _CHANNELS:
        raise PngFormatError(f"Unsupported color type {color_type}: expected 2 (RGB), 3 (indexed) or 6 (RGBA)")

    palette = []
    trns = b""
    idat = bytearray()
    for ctype, payload in chunks:
        if ctype == "PLTE":
            if len(payload) % 3 != 0:
                raise PngFormatError(f"PLTE data length ({len(payload)}) is not a multiple of 3")
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]
        elif ctype == "tRNS":
            trns = payload
        elif ctype == "IDAT":
            idat.extend(payload)

    if color_type == COLOR_TYPE_INDEXED and not palette:
        raise PngFormatError("Indexed PNG is missing its PLTE chunk")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PngFormatError(f"Corrupt IDAT stream: {exc}") from exc

    pixels = _unfilter(raw, width, height, _CHANNELS[color_type])
    return PngImage(width, height, bit_depth, color_type, interlace, chunks, pixels, palette, trns)


def _require_truecolor(image: PngImage, source) -> None:
    if image.color_type not in (COLOR_TYPE_RGB, COLOR_TYPE_RGBA):
        raise PngFormatError(f"Truecolor PNG (color type 2 or 6) required for {source}, got color type {image.color_type}")


def decode_png_rgb(filepath):
    """Decodes a truecolor PNG into (width, height, rows), each row a list of (r, g, b) tuples."""
    image = read_png(filepath)
    _require_truecolor(image, filepath)
    bpp = image.channels
    stride = image.width * bpp
    buf = image.pixels
    rows = []
    for y in range(image.height):
        o = y * stride
        rows.append(list(zip(buf[o:o + stride:bpp], buf[o + 1:o + stride:bpp], buf[o + 2:o + stride:bpp])))
    return image.width, image.height, rows


def decode_png_rgba(filepath):
    """Decodes a truecolor PNG into (width, height, rows), each row a list of (r, g, b, a) tuples."""
    image = read_png(filepath)
    _require_truecolor(image, filepath)
    buf = image.rgba_bytes()
    stride = image.width * 4
    rows = []
    for y in range(image.height):
        o = y * stride
        rows.append(list(zip(buf[o:o + stride:4], buf[o + 1:o + stride:4], buf[o + 2:o + stride:4], buf[o + 3:o + stride:4])))
    return image.width, image.height, rows
