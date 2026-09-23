"""Deterministic raster primitives shared by full-inventory asset generators."""

import hashlib
import math
import os
import re

from png_utils import create_rgba_png


def seed_int(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def clamp(value: int, low: int = 0, high: int = 255) -> int:
    return max(low, min(high, int(value)))


def rgba(rgb, alpha=255):
    return tuple(rgb[:3]) + (alpha,)


def shade(color, amount: int):
    return tuple(clamp(channel + amount) for channel in color[:3]) + (color[3] if len(color) > 3 else 255,)


PALETTES = {
    "meadow": ((49, 91, 62, 255), (105, 148, 77, 255), (202, 184, 105, 255), (48, 119, 135, 255), (38, 43, 54, 255)),
    "water": ((21, 67, 92, 255), (33, 127, 151, 255), (93, 205, 205, 255), (205, 232, 215, 255), (24, 34, 51, 255)),
    "fire": ((93, 31, 31, 255), (190, 61, 37, 255), (241, 137, 45, 255), (255, 222, 108, 255), (47, 29, 34, 255)),
    "snow": ((78, 109, 132, 255), (151, 187, 199, 255), (222, 235, 229, 255), (250, 249, 230, 255), (42, 54, 69, 255)),
    "desert": ((119, 72, 45, 255), (190, 124, 65, 255), (230, 178, 99, 255), (244, 218, 151, 255), (61, 43, 42, 255)),
    "forest": ((31, 69, 51, 255), (52, 111, 60, 255), (111, 151, 76, 255), (196, 191, 104, 255), (31, 38, 38, 255)),
    "night": ((27, 31, 66, 255), (48, 56, 110, 255), (86, 91, 157, 255), (190, 179, 221, 255), (19, 22, 41, 255)),
    "stone": ((57, 59, 66, 255), (91, 94, 101, 255), (139, 139, 132, 255), (198, 184, 146, 255), (37, 37, 44, 255)),
    "holy": ((112, 79, 30, 255), (204, 152, 51, 255), (248, 214, 111, 255), (255, 245, 205, 255), (53, 45, 51, 255)),
    "arcane": ((51, 37, 85, 255), (100, 63, 145, 255), (151, 92, 177, 255), (102, 196, 205, 255), (29, 26, 47, 255)),
}


def palette_for(name: str):
    value = name.lower()
    keyword_groups = (
        ("water", ("water", "sea", "ocean", "river", "wave", "rain", "ice", "aqua", "blue")),
        ("fire", ("fire", "flame", "lava", "burn", "heat", "red")),
        ("snow", ("snow", "frost", "winter", "cold", "white")),
        ("desert", ("desert", "sand", "dry", "waste", "canyon")),
        ("forest", ("forest", "wood", "tree", "grass", "plant", "leaf", "swamp", "moss")),
        ("night", ("night", "dark", "shadow", "space", "cosmos", "moon", "evil", "demon")),
        ("stone", ("stone", "rock", "dungeon", "castle", "ruin", "cave", "metal", "iron")),
        ("holy", ("holy", "light", "angel", "church", "heal", "sun", "victory")),
        ("arcane", ("magic", "arcane", "poison", "spirit", "mystery", "crystal", "dimension")),
    )
    for palette, words in keyword_groups:
        if any(word in value for word in words):
            return PALETTES[palette]
    keys = tuple(PALETTES)
    return PALETTES[keys[seed_int(value) % len(keys)]]


def semantic_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"^\d{3}-", "", stem)
    stem = re.sub(r"_(?:pipo|panop|pochi|uroboros|kagamiyomi|juno|koya|yaeko|momi|komori|isooki|takezo)$", "", stem, flags=re.I)
    stem = re.sub(r"[^0-9A-Za-z]+", "-", stem).strip("-").lower()
    return stem or "unnamed"


class Raster:
    def __init__(self, width: int, height: int, background=(0, 0, 0, 0)):
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid raster size {width}x{height}")
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(background) * (width * height))

    def pixel(self, x: int, y: int, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 4
            self.pixels[offset:offset + 4] = bytes(color)

    def rect(self, x0: int, y0: int, x1: int, y1: int, color):
        x0, x1 = max(0, min(x0, x1)), min(self.width - 1, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(self.height - 1, max(y0, y1))
        if x0 > x1 or y0 > y1:
            return
        row = bytes(color) * (x1 - x0 + 1)
        for y in range(y0, y1 + 1):
            start = (y * self.width + x0) * 4
            self.pixels[start:start + len(row)] = row

    def line(self, x0: int, y0: int, x1: int, y1: int, color, width: int = 1):
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        err = dx + dy
        radius = max(0, width // 2)
        while True:
            self.rect(x0 - radius, y0 - radius, x0 + radius, y0 + radius, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * err
            if twice >= dy:
                err += dy
                x0 += sx
            if twice <= dx:
                err += dx
                y0 += sy

    def ellipse(self, cx: int, cy: int, rx: int, ry: int, color):
        rx, ry = max(1, rx), max(1, ry)
        for y in range(max(0, cy - ry), min(self.height, cy + ry + 1)):
            dy = (y - cy) / ry
            span = int(rx * math.sqrt(max(0.0, 1.0 - dy * dy)))
            self.rect(cx - span, y, cx + span, y, color)

    def triangle(self, points, color):
        (x1, y1), (x2, y2), (x3, y3) = points
        min_y, max_y = max(0, min(y1, y2, y3)), min(self.height - 1, max(y1, y2, y3))
        area = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if area == 0:
            return
        for y in range(min_y, max_y + 1):
            xs = []
            for (ax, ay), (bx, by) in (((x1, y1), (x2, y2)), ((x2, y2), (x3, y3)), ((x3, y3), (x1, y1))):
                if ay == by or y < min(ay, by) or y > max(ay, by):
                    continue
                xs.append(round(ax + (y - ay) * (bx - ax) / (by - ay)))
            if len(xs) >= 2:
                self.rect(min(xs), y, max(xs), y, color)

    def vertical_gradient(self, top, bottom):
        denominator = max(1, self.height - 1)
        for y in range(self.height):
            mix = y / denominator
            color = tuple(round(top[i] * (1 - mix) + bottom[i] * mix) for i in range(4))
            self.rect(0, y, self.width - 1, y, color)

    def png(self) -> bytes:
        return create_rgba_png(self.width, self.height, bytes(self.pixels))
