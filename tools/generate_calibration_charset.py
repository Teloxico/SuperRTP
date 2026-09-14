#!/usr/bin/env python3
"""
Clean-Room Synthetic Calibration CharSet Generator for SuperRTP.

Generates a test-only canonical walking character sprite sheet compliant with
RPG Maker 2000 specifications:
- Total dimensions: 288 x 256 pixels
- Character layout: 8 characters arranged in a 4x2 grid (72 x 128 per character)
- Frame layout: 3 columns x 4 rows per character (24 x 32 per frame)
  - Col 0: Left step, Col 1: Standing (idle), Col 2: Right step
  - Row 0: Facing Down, Row 1: Facing Left, Row 2: Facing Right, Row 3: Facing Up
- Pixel format: PNG 8-bit indexed colormap (Color Type 3)
- Palette index 0: Transparent background (tRNS alpha 0)
- Visual primitives: Pure geometric directional arrows and step markers
- Provenance: 100% synthetic, zero proprietary RTP creative assets
"""

import os
import sys
import struct
import zlib
import hashlib

def create_png(width, height, palette, pixel_indices):
    """
    Constructs an 8-bit indexed PNG with a tRNS chunk ensuring index 0 is transparent.
    """
    def chunk(chunk_type, data):
        c_type = chunk_type.encode('ascii')
        crc = zlib.crc32(c_type + data) & 0xffffffff
        return struct.pack('>I', len(data)) + c_type + data + struct.pack('>I', crc)

    # PNG Signature
    png_sig = b'\x89PNG\r\n\x1a\n'

    # IHDR: width, height, bit depth (8), color type (3 = indexed), compression (0), filter (0), interlace (0)
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)
    ihdr_chunk = chunk('IHDR', ihdr_data)

    # PLTE: palette of RGB triples (max 256 entries)
    plte_data = bytearray()
    for r, g, b in palette:
        plte_data.extend([r, g, b])
    plte_chunk = chunk('PLTE', bytes(plte_data))

    # tRNS: transparency chunk. Palette index 0 has alpha 0, others default to 255.
    trns_data = b'\x00'
    trns_chunk = chunk('tRNS', trns_data)

    # IDAT: image data with scanline filter type 0 (None)
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # Filter type 0
        start = y * width
        raw_data.extend(pixel_indices[start:start + width])

    compressed_idat = zlib.compress(bytes(raw_data), level=9)
    idat_chunk = chunk('IDAT', compressed_idat)

    # IEND
    iend_chunk = chunk('IEND', b'')

    return png_sig + ihdr_chunk + plte_chunk + trns_chunk + idat_chunk + iend_chunk

def generate_calibration_charset():
    width = 288
    height = 256
    pixels = bytearray(width * height)

    # Define color schemes for 8 character slots (Slots 0 to 7)
    # Each slot has: (body_color, outline_color, accent_color, foot_color)
    slot_themes = [
        # Slot 0 (Hero / Actor 1): Cyan / Amber / Gold
        {"body": (0, 210, 230), "outline": (10, 40, 70), "accent": (255, 230, 80), "foot": (240, 160, 20)},
        # Slot 1: Emerald / Forest / Lemon
        {"body": (40, 220, 120), "outline": (10, 60, 30), "accent": (220, 255, 80), "foot": (180, 200, 30)},
        # Slot 2: Crimson / Maroon / Orange
        {"body": (240, 60, 60), "outline": (70, 10, 20), "accent": (255, 180, 60), "foot": (220, 100, 30)},
        # Slot 3: Indigo / Deep Blue / Sky
        {"body": (80, 120, 250), "outline": (20, 20, 80), "accent": (140, 220, 255), "foot": (60, 80, 200)},
        # Slot 4: Magenta / Dark Purple / Pink
        {"body": (220, 60, 200), "outline": (60, 10, 60), "accent": (255, 160, 240), "foot": (180, 40, 140)},
        # Slot 5: Amber / Rust / Cream
        {"body": (250, 160, 30), "outline": (70, 40, 10), "accent": (255, 240, 160), "foot": (200, 110, 20)},
        # Slot 6: Teal / Slate / Mint
        {"body": (30, 200, 190), "outline": (20, 50, 60), "accent": (180, 255, 230), "foot": (20, 140, 130)},
        # Slot 7: Silver / Charcoal / Bronze
        {"body": (210, 215, 220), "outline": (50, 55, 60), "accent": (255, 255, 255), "foot": (150, 110, 70)},
    ]

    # Build palette:
    # Index 0: Transparent (0, 0, 0)
    # Index 1: Neutral dark grid / calibration border (30, 30, 35)
    palette = [
        (0, 0, 0),      # 0: Transparent
        (30, 30, 35),   # 1: Frame calibration corner marker
    ]

    slot_color_indices = []
    for theme in slot_themes:
        b_idx = len(palette)
        palette.append(theme["body"])
        o_idx = len(palette)
        palette.append(theme["outline"])
        a_idx = len(palette)
        palette.append(theme["accent"])
        f_idx = len(palette)
        palette.append(theme["foot"])
        slot_color_indices.append({
            "body": b_idx,
            "outline": o_idx,
            "accent": a_idx,
            "foot": f_idx,
        })

    # Render each character
    for char_idx in range(8):
        char_grid_x = char_idx % 4
        char_grid_y = char_idx // 4
        char_base_x = char_grid_x * 72
        char_base_y = char_grid_y * 128
        colors = slot_color_indices[char_idx]

        for row in range(4):        # 4 directions
            for col in range(3):    # 3 walking frames
                fx0 = char_base_x + col * 24
                fy0 = char_base_y + row * 32

                # Helper to set pixel inside cell
                def set_px(lx, ly, color_idx):
                    if 0 <= lx < 24 and 0 <= ly < 32:
                        pixels[(fy0 + ly) * width + (fx0 + lx)] = color_idx

                # 1. Subtle corner calibration ticks (2x2 at corners)
                # Allows immediate verification that tile alignment is exact
                set_px(0, 0, 1)
                set_px(1, 0, 1)
                set_px(0, 1, 1)
                set_px(23, 0, 1)
                set_px(22, 0, 1)
                set_px(23, 1, 1)
                set_px(0, 31, 1)
                set_px(1, 31, 1)
                set_px(0, 30, 1)
                set_px(23, 31, 1)
                set_px(22, 31, 1)
                set_px(23, 30, 1)

                # 2. Feet / Step markers at bottom (ly = 24..28)
                # Col 0: Left step (left foot forward/lower, right foot back)
                # Col 1: Standing (center feet symmetric)
                # Col 2: Right step (right foot forward/lower, left foot back)
                if col == 1:  # Center / Idle standing
                    for ly in range(25, 28):
                        for lx in range(7, 10):
                            set_px(lx, ly, colors["foot"])
                        for lx in range(14, 17):
                            set_px(lx, ly, colors["foot"])
                elif col == 0:  # Left step forward
                    for ly in range(26, 29):  # Left foot lower/forward
                        for lx in range(6, 10):
                            set_px(lx, ly, colors["foot"])
                    for ly in range(24, 26):  # Right foot higher/back
                        for lx in range(14, 17):
                            set_px(lx, ly, colors["foot"])
                elif col == 2:  # Right step forward
                    for ly in range(24, 26):  # Left foot higher/back
                        for lx in range(7, 10):
                            set_px(lx, ly, colors["foot"])
                    for ly in range(26, 29):  # Right foot lower/forward
                        for lx in range(14, 18):
                            set_px(lx, ly, colors["foot"])

                # 3. Geometric Directional Arrow Body
                # Row 0: Facing Down (V)
                # Row 1: Facing Left (<)
                # Row 2: Facing Right (>)
                # Row 3: Facing Up (^)
                if row == 0:  # Down
                    # Draw a wide downward chevron arrow
                    for ly in range(5, 23):
                        # Arrow tapers down towards tip at (11.5, 21)
                        if ly <= 13:
                            # Upper wings
                            left_edge = max(3, 11 - (ly - 5) * 1)
                            right_edge = min(20, 12 + (ly - 5) * 1)
                            notch_left = 11 - (ly - 5) // 2
                            notch_right = 12 + (ly - 5) // 2
                            for lx in range(left_edge, right_edge + 1):
                                if ly < 9 and notch_left <= lx <= notch_right:
                                    continue  # inner notch
                                is_outline = (lx == left_edge or lx == right_edge or
                                              (ly >= 8 and (lx == notch_left or lx == notch_right)))
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                        else:
                            # Lower tip
                            span = 21 - ly
                            left_edge = 11 - span
                            right_edge = 12 + span
                            for lx in range(left_edge, right_edge + 1):
                                is_outline = (lx == left_edge or lx == right_edge or ly == 21)
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                    # Center accent core
                    for ly in range(11, 14):
                        for lx in range(10, 14):
                            set_px(lx, ly, colors["accent"])

                elif row == 1:  # Left
                    # Draw a pointing-left chevron arrow
                    for lx in range(4, 20):
                        if lx <= 12:
                            # Tip pointing left towards x=4
                            span = lx - 4
                            top_edge = 13 - span
                            bottom_edge = 14 + span
                            for ly in range(top_edge, bottom_edge + 1):
                                is_outline = (lx == 4 or ly == top_edge or ly == bottom_edge)
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                        else:
                            # Back notch
                            span = 19 - lx
                            top_edge = 6 + (12 - lx) // 2
                            bottom_edge = 21 - (12 - lx) // 2
                            inner_top = 10 + span // 2
                            inner_bot = 17 - span // 2
                            for ly in range(6, 22):
                                if inner_top <= ly <= inner_bot and lx > 14:
                                    continue
                                is_outline = (lx == 19 or ly == 6 or ly == 21 or
                                              (lx <= 15 and (ly == inner_top or ly == inner_bot)))
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                    # Center accent core
                    for ly in range(12, 16):
                        for lx in range(9, 13):
                            set_px(lx, ly, colors["accent"])

                elif row == 2:  # Right
                    # Draw a pointing-right chevron arrow
                    for lx in range(4, 20):
                        if lx >= 11:
                            # Tip pointing right towards x=19
                            span = 19 - lx
                            top_edge = 13 - span
                            bottom_edge = 14 + span
                            for ly in range(top_edge, bottom_edge + 1):
                                is_outline = (lx == 19 or ly == top_edge or ly == bottom_edge)
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                        else:
                            # Back notch
                            span = lx - 4
                            inner_top = 10 + span // 2
                            inner_bot = 17 - span // 2
                            for ly in range(6, 22):
                                if inner_top <= ly <= inner_bot and lx < 9:
                                    continue
                                is_outline = (lx == 4 or ly == 6 or ly == 21 or
                                              (lx >= 8 and (ly == inner_top or ly == inner_bot)))
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                    # Center accent core
                    for ly in range(12, 16):
                        for lx in range(11, 15):
                            set_px(lx, ly, colors["accent"])

                elif row == 3:  # Up
                    # Draw an upward pointing chevron arrow
                    for ly in range(5, 23):
                        if ly <= 13:
                            # Pointing up towards tip at (11.5, 5)
                            span = ly - 5
                            left_edge = 11 - span
                            right_edge = 12 + span
                            for lx in range(left_edge, right_edge + 1):
                                is_outline = (ly == 5 or lx == left_edge or lx == right_edge)
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                        else:
                            # Lower wings and inner notch
                            span = ly - 13
                            left_edge = 3 + span // 2
                            right_edge = 20 - span // 2
                            notch_left = 11 - span
                            notch_right = 12 + span
                            for lx in range(3, 21):
                                if ly > 15 and notch_left <= lx <= notch_right:
                                    continue
                                is_outline = (lx == 3 or lx == 20 or ly == 22 or
                                              (ly <= 19 and (lx == notch_left or lx == notch_right)))
                                set_px(lx, ly, colors["outline"] if is_outline else colors["body"])
                    # Center accent core
                    for ly in range(11, 14):
                        for lx in range(10, 14):
                            set_px(lx, ly, colors["accent"])

    png_bytes = create_png(width, height, palette, pixels)
    return png_bytes

def main():
    target_path = "registry/assets/test_calibration_walking_character.png"
    if len(sys.argv) > 1:
        target_path = sys.argv[1]

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    png_bytes = generate_calibration_charset()

    with open(target_path, "wb") as f:
        f.write(png_bytes)

    sha256_hash = hashlib.sha256(png_bytes).hexdigest()
    print(f"Generated canonical calibration asset: {target_path}")
    print(f"Size: {len(png_bytes)} bytes")
    print(f"SHA-256: {sha256_hash}")

if __name__ == "__main__":
    main()
