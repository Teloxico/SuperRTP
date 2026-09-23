"""Clean-room procedural visual assets for every inventoried compatibility path."""

from dataclasses import dataclass
import os
import re
import struct
import subprocess

import transforms
from asset_generation.procedural_common import Raster, palette_for, seed_int, semantic_stem, shade


@dataclass(frozen=True)
class VisualPolicy:
    width: int
    height: int
    family: str
    indexed: bool = False


def _rgss_system_policy(path: str, ace: bool) -> VisualPolicy:
    name = os.path.splitext(os.path.basename(path))[0].lower()
    fixed = {
        "balloon": (256, 320, "effect"),
        "battlestart": (544, 416, "transition"),
        "gameover": (544, 416, "scene"),
        "iconset": (384, 384, "icon-atlas"),
        "messageback": (544, 160, "ui"),
        "shadow": (32, 16, "mask"),
        "title": (544, 416, "scene"),
        "window": (128, 128, "ui"),
        "battlefloor": (544, 416, "scene"),
    }
    if name in fixed:
        return VisualPolicy(*fixed[name])
    if name.startswith("tilea1"):
        return VisualPolicy(512 if not ace else 768, 384 if not ace else 576, "tiles")
    if name.startswith("tilea2"):
        return VisualPolicy(512 if not ace else 768, 384 if not ace else 576, "tiles")
    if name.startswith("tilea3"):
        return VisualPolicy(512 if not ace else 768, 256 if not ace else 384, "tiles")
    if name.startswith("tilea4"):
        return VisualPolicy(512 if not ace else 768, 480 if not ace else 720, "tiles")
    if name.startswith("tilea5"):
        return VisualPolicy(256 if not ace else 384, 512 if not ace else 768, "tiles")
    if re.match(r"tile[b-e]", name):
        return VisualPolicy(512 if not ace else 768, 512 if not ace else 768, "tiles")
    return VisualPolicy(256, 256, "ui")


def visual_policy(engine: str, path: str) -> VisualPolicy:
    category = "/".join(path.split("/")[:-1])
    basename = os.path.basename(path)
    lower = path.lower()
    indexed = engine in ("rm2000", "rm2003")
    if path.lower().endswith(".ico"):
        return VisualPolicy(64, 64, "icon")
    if engine in ("rm2000", "rm2003"):
        table = {
            "Backdrop": (320, 160 if engine == "rm2000" else 240, "scene"),
            "Battle": (480, 480, "effect"),
            "BattleCharSet": (144, 384, "battle-character"),
            "BattleWeapon": (192, 512, "weapon-sheet"),
            "CharSet": (288, 256, "charset"),
            "ChipSet": (480, 256, "tiles"),
            "FaceSet": (192, 192, "faces"),
            "GameOver": (320, 240, "scene"),
            "Monster": (160, 160, "creature"),
            "Panorama": (320, 240, "scene"),
            "System": (160, 80, "ui"),
            "System2": (80, 96, "ui"),
            "Title": (320, 240, "scene"),
        }
        return VisualPolicy(*table[category], indexed=indexed)
    if engine == "rmxp":
        table = {
            "Graphics/Animations": (960, 960, "effect"),
            "Graphics/Autotiles": (96, 128, "autotile"),
            "Graphics/Battlebacks": (640, 320, "scene"),
            "Graphics/Battlers": (256, 256, "creature"),
            "Graphics/Characters": (128, 192, "charset-xp"),
            "Graphics/Fogs": (256, 256, "fog"),
            "Graphics/Gameovers": (640, 480, "scene"),
            "Graphics/Icons": (24, 24, "icon"),
            "Graphics/Panoramas": (640, 480, "scene"),
            "Graphics/Tilesets": (256, 640, "tiles"),
            "Graphics/Titles": (640, 480, "scene"),
            "Graphics/Transitions": (640, 480, "transition"),
            "Graphics/Windowskins": (192, 128, "ui"),
        }
        return VisualPolicy(*table[category])
    if engine in ("rmvx", "rmvxace"):
        if category == "Graphics/Animations":
            return VisualPolicy(960, 960, "effect")
        if category in ("Graphics/Battlebacks1", "Graphics/Battlebacks2"):
            return VisualPolicy(580, 444, "scene")
        if category == "Graphics/Battlers":
            return VisualPolicy(256, 256, "creature")
        if category == "Graphics/Characters":
            return VisualPolicy(96, 128, "charset-vx-single") if "$" in basename else VisualPolicy(384, 256, "charset-vx")
        if category == "Graphics/Faces":
            return VisualPolicy(384, 192, "faces-vx")
        if category == "Graphics/Parallaxes":
            return VisualPolicy(544, 416, "scene")
        if category in ("Graphics/Titles1", "Graphics/Titles2"):
            return VisualPolicy(544, 416, "scene" if category.endswith("1") else "overlay")
        if category == "Graphics/Tilesets":
            tile_name = os.path.splitext(basename)[0].split("_")[-1]
            return _rgss_system_policy("Tile" + tile_name + ".png", True)
        if category == "Graphics/System":
            return _rgss_system_policy(path, engine == "rmvxace")
    if engine == "wolf":
        if category == "Data/BasicData":
            return VisualPolicy(24, 24, "icon")
        if category == "Data/BattleEffect":
            return VisualPolicy(480, 480, "effect")
        if category == "Data/CharaChip":
            return VisualPolicy(72, 128, "charset-vx-single")
        if category == "Data/EnemyGraphic":
            return VisualPolicy(256, 256, "creature")
        if category == "Data/Fog_BackGround":
            return VisualPolicy(640, 480, "scene")
        if category == "Data/MapChip":
            return VisualPolicy(80, 160, "autotile") if basename.lower().startswith("auto_") else VisualPolicy(256, 512, "tiles")
        if category == "Data/Picture":
            return VisualPolicy(200, 200, "portrait")
        if category == "Data/SystemFile":
            name = os.path.splitext(basename)[0].lower()
            if "slash200x480" in name:
                return VisualPolicy(200, 480, "mask")
            if "circle120" in name or "spray120" in name:
                return VisualPolicy(120, 120, "mask")
            if name == "titlegraphic":
                return VisualPolicy(640, 480, "scene")
            if name == "transition_fade":
                return VisualPolicy(640, 480, "transition")
            if name.startswith("windowbase"):
                return VisualPolicy(128, 128, "ui")
            if name == "charashade_8dir":
                return VisualPolicy(96, 32, "mask")
            return VisualPolicy(32, 32, "icon")
    raise ValueError(f"No visual policy for {engine}:{path}")


def _draw_scene(canvas: Raster, name: str, palette, seed: int):
    p0, p1, p2, p3, dark = palette
    canvas.vertical_gradient(shade(p1, -20), shade(p3, 10))
    horizon = canvas.height * (52 + seed % 17) // 100
    canvas.rect(0, horizon, canvas.width - 1, canvas.height - 1, p0)
    # Layered original terrain silhouettes.
    for layer in range(4):
        base = horizon + layer * max(2, canvas.height // 20)
        color = shade(p0, -18 + layer * 8)
        step = max(16, canvas.width // (6 + layer))
        offset = (seed >> (layer * 5)) % step
        for x in range(-step + offset, canvas.width + step, step):
            peak = base - canvas.height // (8 + layer * 2) - ((seed + x * 7) % max(2, canvas.height // 12))
            canvas.triangle(((x - step, base), (x, peak), (x + step, base)), color)
    lower = name.lower()
    if any(word in lower for word in ("sea", "water", "ocean", "river", "beach", "ship")):
        canvas.rect(0, horizon + canvas.height // 10, canvas.width - 1, canvas.height - 1, p1)
        for y in range(horizon + canvas.height // 8, canvas.height, max(3, canvas.height // 24)):
            canvas.line((seed + y) % 13, y, canvas.width - 1 - ((seed + y) % 19), y, p3)
    if any(word in lower for word in ("forest", "wood", "grass", "field", "swamp")):
        for index in range(12):
            x = (seed // (index + 1) + index * 67) % canvas.width
            y = horizon + (index * 29) % max(1, canvas.height - horizon)
            trunk = max(2, canvas.width // 100)
            canvas.rect(x - trunk // 2, y, x + trunk // 2, y + canvas.height // 9, dark)
            canvas.ellipse(x, y, canvas.width // 35 + index % 3, canvas.height // 18 + index % 4, p1)
    if any(word in lower for word in ("dungeon", "castle", "town", "city", "shrine", "temple", "bridge", "ruin")):
        bw, bh = canvas.width // 3, canvas.height // 3
        bx, by = canvas.width // 2 - bw // 2, horizon - bh // 2
        canvas.rect(bx, by, bx + bw, by + bh, shade(p0, -10))
        canvas.triangle(((bx - 3, by), (bx + bw // 2, by - bh // 3), (bx + bw + 3, by)), p2)
        canvas.rect(bx + bw // 2 - bw // 10, by + bh // 2, bx + bw // 2 + bw // 10, by + bh, dark)
    # Stars, petals, or sparks add path-specific detail without text.
    for index in range(18):
        x = (seed + index * 977) % canvas.width
        y = ((seed >> 8) + index * 499) % max(1, horizon)
        canvas.pixel(x, y, p3)


def _draw_character(canvas: Raster, ox: int, oy: int, fw: int, fh: int, palette, seed: int, direction: int, phase: int):
    p0, p1, p2, p3, dark = palette
    cx = ox + fw // 2
    top = oy + max(1, fh // 12)
    head_rx, head_ry = max(2, fw // 7), max(2, fh // 8)
    step = (-1, 0, 1, 0)[phase % 4]
    side = 1 if direction == 1 else -1 if direction == 3 else 0
    canvas.ellipse(cx + side, top + head_ry, head_rx + 1, head_ry + 1, dark)
    canvas.ellipse(cx + side, top + head_ry, head_rx, head_ry, p3)
    canvas.rect(cx - fw // 5, top, cx + fw // 5, top + max(1, fh // 12), p2)
    body_y = top + head_ry * 2
    canvas.rect(cx - fw // 5, body_y, cx + fw // 5, body_y + fh // 3, dark)
    canvas.rect(cx - fw // 6, body_y + 1, cx + fw // 6, body_y + fh // 3 - 1, p0)
    canvas.rect(cx - fw // 4, body_y + 2, cx - fw // 5, body_y + fh // 3, p1)
    canvas.rect(cx + fw // 5, body_y + 2, cx + fw // 4, body_y + fh // 3, p1)
    foot_y = oy + fh - max(2, fh // 16) - 1
    canvas.line(cx - fw // 8, body_y + fh // 3, cx - fw // 8 + min(0, step), foot_y, dark, max(1, fw // 12))
    canvas.line(cx + fw // 8, body_y + fh // 3, cx + fw // 8 + max(0, step), foot_y, dark, max(1, fw // 12))
    if seed & 1:
        canvas.line(cx - fw // 5, body_y + 2, cx + fw // 5, body_y + fh // 3, p2)
    if seed & 2:
        canvas.rect(cx + fw // 5, body_y + fh // 5, cx + fw // 3, body_y + fh // 3, p2)
    if direction != 0:
        canvas.pixel(cx + side + (head_rx // 2 if direction == 1 else -head_rx // 2 if direction == 3 else -1), top + head_ry, dark)
        if direction == 2:
            canvas.pixel(cx + 1, top + head_ry, dark)


def _draw_object_frame(canvas: Raster, ox: int, oy: int, fw: int, fh: int, name: str, palette, seed: int,
                       direction: int, phase: int):
    p0, p1, p2, p3, dark = palette
    lower = name.lower()
    cx, cy = ox + fw // 2, oy + fh // 2
    margin = max(2, fw // 8)
    if any(word in lower for word in ("gate", "door", "portcullis")):
        left, right = ox + margin, ox + fw - margin - 1
        top, bottom = oy + margin, oy + fh - 2
        canvas.rect(left, top, right, bottom, dark)
        inset = max(1, fw // 16)
        canvas.rect(left + inset, top + inset, right - inset, bottom, p0)
        opening = phase * max(1, (bottom - top) // 5)
        for x in range(left + inset, right, max(2, fw // 6)):
            canvas.rect(x, top + inset, min(right - inset, x + max(1, fw // 20)), bottom - opening, p2)
        canvas.line(left, cy, right, cy, p1, max(1, fh // 24))
    elif "chest" in lower or "treasure" in lower:
        top = oy + fh // 3 + (0 if phase == 1 else phase - 1)
        canvas.rect(ox + margin, top, ox + fw - margin - 1, oy + fh - margin, dark)
        canvas.rect(ox + margin + 2, top + 2, ox + fw - margin - 3, oy + fh - margin - 2, p0)
        lid_y = top - (fh // 7 if phase == 2 else 0)
        canvas.rect(ox + margin, lid_y, ox + fw - margin - 1, lid_y + max(2, fh // 7), p2)
        canvas.rect(cx - 1, top + fh // 6, cx + 1, top + fh // 4, p3)
    elif "crystal" in lower:
        canvas.triangle(((cx, oy + margin), (ox + fw - margin, cy), (cx, oy + fh - margin)), p1)
        canvas.triangle(((cx, oy + margin), (ox + margin, cy), (cx, oy + fh - margin)), p3)
        canvas.line(cx, oy + margin, cx, oy + fh - margin, dark)
    elif any(word in lower for word in ("flame", "fire", "torch")):
        wobble = phase - 1
        canvas.triangle(((cx + wobble, oy + margin), (ox + margin, oy + fh - margin),
                         (ox + fw - margin, oy + fh - margin)), p1)
        canvas.ellipse(cx - wobble, oy + fh * 2 // 3, max(2, fw // 6), max(2, fh // 5), p3)
        canvas.pixel(cx, oy + fh - margin, p2)
    elif any(word in lower for word in ("vehicle", "ship", "boat", "airship")):
        canvas.rect(ox + margin, cy, ox + fw - margin - 1, oy + fh - margin, dark)
        canvas.triangle(((ox + margin, cy), (cx, oy + margin), (cx, cy)), p3)
        canvas.triangle(((cx, cy), (cx, oy + margin), (ox + fw - margin, cy)), p2)
        canvas.line(cx, oy + margin, cx, oy + fh - margin, dark)
    else:
        # Generic project event: a readable pillar/orb rather than a fake person.
        canvas.rect(cx - fw // 5, oy + fh // 3, cx + fw // 5, oy + fh - margin, dark)
        canvas.rect(cx - fw // 6, oy + fh // 3 + 1, cx + fw // 6, oy + fh - margin - 1, p0)
        canvas.ellipse(cx, oy + fh // 3, max(2, fw // 5), max(2, fh // 7), p2)


def _draw_small_creature_frame(canvas: Raster, ox: int, oy: int, fw: int, fh: int, palette, seed: int,
                               direction: int, phase: int):
    p0, p1, p2, p3, dark = palette
    cx = ox + fw // 2 + (phase - 1)
    cy = oy + fh * 2 // 3
    rx, ry = max(3, fw // 3), max(3, fh // 5)
    canvas.ellipse(cx, cy, rx, ry, dark)
    canvas.ellipse(cx, cy, max(2, rx - 1), max(2, ry - 1), p0)
    canvas.ellipse(cx, cy - ry, max(2, rx // 2), max(2, ry // 2), p1)
    eye_x = cx + (rx // 4 if direction == 1 else -rx // 4 if direction == 3 else 0)
    if direction != 0:
        canvas.pixel(eye_x - 1, cy - ry, p3)
        canvas.pixel(eye_x + 1, cy - ry, p3)
    if seed & 1:
        canvas.triangle(((cx - rx // 2, cy - ry), (cx - rx, cy - ry * 2), (cx, cy - ry)), p2)
        canvas.triangle(((cx + rx // 2, cy - ry), (cx + rx, cy - ry * 2), (cx, cy - ry)), p2)
    canvas.line(cx - rx // 2, cy + ry, cx - rx // 2 - (1 if phase == 0 else 0), oy + fh - 2, dark)
    canvas.line(cx + rx // 2, cy + ry, cx + rx // 2 + (1 if phase == 2 else 0), oy + fh - 2, dark)


def _draw_charset(canvas: Raster, name: str, policy: VisualPolicy, palette, seed: int):
    if policy.family == "charset-xp":
        chars_x, chars_y, cols, rows = 1, 1, 4, 4
    elif policy.family == "charset-vx-single":
        chars_x, chars_y, cols, rows = 1, 1, 3, 4
    else:
        chars_x, chars_y, cols, rows = 4, 2, 3, 4
    fw, fh = policy.width // (chars_x * cols), policy.height // (chars_y * rows)
    lower = name.lower()
    object_sheet = any(word in lower for word in (
        "gate", "door", "chest", "crystal", "flame", "fire", "torch", "object", "vehicle", "ship", "boat", "coffin",
    ))
    creature_sheet = any(word in lower for word in (
        "animal", "monster", "slime", "bat", "bird", "cat", "dog", "cow", "chicken", "wolf", "dragon", "goblin", "rat",
    ))
    for char_index in range(chars_x * chars_y):
        char_seed = seed_int(f"{name}:{char_index}")
        char_palette = palette_for(f"{name}:{char_index}")
        base_x = (char_index % chars_x) * cols * fw
        base_y = (char_index // chars_x) * rows * fh
        for row in range(rows):
            for col in range(cols):
                phase = (0, 1, 2, 1)[col] if cols == 4 else col
                frame = (base_x + col * fw, base_y + row * fh, fw, fh)
                if object_sheet:
                    _draw_object_frame(canvas, *frame, name, char_palette, char_seed, row, phase)
                elif creature_sheet:
                    _draw_small_creature_frame(canvas, *frame, char_palette, char_seed, row, phase)
                else:
                    _draw_character(canvas, *frame, char_palette, char_seed, row, phase)


def _draw_faces(canvas: Raster, name: str, policy: VisualPolicy, palette, seed: int):
    if policy.family == "portrait":
        cols, rows = 1, 1
    elif policy.family == "faces-vx":
        cols, rows = 4, 2
    else:
        cols, rows = 4, 4
    fw, fh = policy.width // cols, policy.height // rows
    for index in range(cols * rows):
        colors = palette_for(f"{name}:{index}")
        p0, p1, p2, p3, dark = colors
        ox, oy = (index % cols) * fw, (index // cols) * fh
        canvas.rect(ox, oy, ox + fw - 1, oy + fh - 1, shade(p0, -25))
        cx, cy = ox + fw // 2, oy + fh // 2
        canvas.ellipse(cx, cy, fw // 3, fh // 2 - max(2, fh // 12), dark)
        canvas.ellipse(cx, cy, fw // 3 - 2, fh // 2 - max(4, fh // 10), p3)
        canvas.rect(cx - fw // 3, oy + fh // 8, cx + fw // 3, oy + fh // 3, p2)
        canvas.pixel(cx - fw // 9, cy, dark)
        canvas.pixel(cx + fw // 9, cy, dark)
        canvas.line(cx - fw // 10, cy + fh // 7, cx + fw // 10, cy + fh // 7, p1)


def _draw_creature(canvas: Raster, name: str, palette, seed: int):
    p0, p1, p2, p3, dark = palette
    cx, cy = canvas.width // 2, canvas.height * 58 // 100
    rx, ry = canvas.width // 3, canvas.height // 4
    lower = name.lower()
    if any(word in lower for word in ("bird", "angel", "bat", "dragon", "griff", "wing")):
        canvas.triangle(((cx - rx // 2, cy), (cx - rx, cy - ry), (cx - rx, cy + ry // 2)), shade(p1, -10))
        canvas.triangle(((cx + rx // 2, cy), (cx + rx, cy - ry), (cx + rx, cy + ry // 2)), shade(p1, -10))
    for side in (-1, 1):
        if seed & (1 if side < 0 else 2):
            canvas.triangle(((cx + side * rx // 3, cy - ry), (cx + side * rx // 2, cy - ry * 3 // 2), (cx + side * rx // 8, cy - ry)), p2)
    canvas.ellipse(cx, cy, rx, ry, dark)
    canvas.ellipse(cx, cy, rx - max(2, rx // 12), ry - max(2, ry // 12), p0)
    canvas.ellipse(cx, cy - ry, rx // 2, ry // 2, dark)
    canvas.ellipse(cx, cy - ry, max(2, rx // 2 - 2), max(2, ry // 2 - 2), p1)
    eye_y = cy - ry
    canvas.ellipse(cx - rx // 6, eye_y, max(1, rx // 16), max(1, ry // 12), p3)
    canvas.ellipse(cx + rx // 6, eye_y, max(1, rx // 16), max(1, ry // 12), p3)
    for leg in (-2, -1, 1, 2):
        lx = cx + leg * rx // 4
        canvas.line(lx, cy + ry // 2, lx + (leg % 2) * rx // 8, cy + ry + ry // 2, dark, max(1, canvas.width // 50))
    if "slime" in lower or "jelly" in lower:
        canvas.rect(cx - rx, cy, cx + rx, cy + ry, p0)
    if seed & 4:
        canvas.line(cx + rx, cy, min(canvas.width - 1, cx + rx + rx // 2), cy - ry // 2, p2, max(1, canvas.width // 60))


def _draw_effect(canvas: Raster, name: str, palette, seed: int):
    p0, p1, p2, p3, dark = palette
    cols = rows = 5
    fw, fh = canvas.width // cols, canvas.height // rows
    for index in range(cols * rows):
        ox, oy = (index % cols) * fw, (index // cols) * fh
        cx, cy = ox + fw // 2, oy + fh // 2
        radius = max(2, min(fw, fh) * (index % 5 + 1) // 12)
        color = (p1, p2, p3)[index % 3]
        if seed & 1:
            canvas.ellipse(cx, cy, radius, max(1, radius // 4), color)
            canvas.ellipse(cx, cy, max(1, radius - max(2, fw // 30)), max(1, radius // 4 - 1), (0, 0, 0, 0))
        else:
            canvas.line(cx - radius, cy + radius, cx + radius, cy - radius, dark, max(1, fw // 32))
            canvas.line(cx - radius + 2, cy + radius, cx + radius, cy - radius + 2, color, max(1, fw // 48))
        for spark in range(5):
            angle_seed = seed + index * 31 + spark * 17
            sx = cx + ((angle_seed % (radius * 2 + 1)) - radius)
            sy = cy + (((angle_seed >> 5) % (radius * 2 + 1)) - radius)
            canvas.ellipse(sx, sy, max(1, fw // 96), max(1, fh // 96), p3)


def _draw_tiles(canvas: Raster, name: str, palette, seed: int, tile=16):
    p0, p1, p2, p3, dark = palette
    for ty in range(0, canvas.height, tile):
        for tx in range(0, canvas.width, tile):
            index = tx // tile + (ty // tile) * max(1, canvas.width // tile)
            base = (p0, p1, p2, shade(p0, 18))[index % 4]
            canvas.rect(tx, ty, min(canvas.width - 1, tx + tile - 1), min(canvas.height - 1, ty + tile - 1), base)
            mode = (seed + index) % 5
            if mode == 0:
                canvas.line(tx, ty + tile // 2, tx + tile - 1, ty + tile // 2, shade(base, 20))
            elif mode == 1:
                canvas.rect(tx + 2, ty + 2, min(tx + tile - 3, canvas.width - 1), min(ty + tile - 3, canvas.height - 1), shade(base, -15))
            elif mode == 2:
                canvas.line(tx, ty, tx + tile - 1, ty + tile - 1, p3)
            elif mode == 3:
                canvas.ellipse(tx + tile // 2, ty + tile // 2, max(1, tile // 5), max(1, tile // 5), p2)
            else:
                canvas.pixel(tx + (seed + index * 3) % tile, ty + (seed // 7 + index * 5) % tile, dark)


def _draw_icon(canvas: Raster, name: str, palette, seed: int, atlas=False):
    p0, p1, p2, p3, dark = palette
    cell = 24
    for oy in range(0, canvas.height, cell):
        for ox in range(0, canvas.width, cell):
            local = seed + ox * 17 + oy * 31
            cx, cy = ox + min(cell, canvas.width - ox) // 2, oy + min(cell, canvas.height - oy) // 2
            radius = max(2, min(cell, canvas.width - ox, canvas.height - oy) // 3)
            lower = name.lower()
            if any(word in lower for word in ("weapon", "sword", "blade", "axe", "spear", "bow", "rod", "staff")):
                canvas.line(cx - radius, cy + radius, cx + radius, cy - radius, dark, max(2, radius // 3))
                canvas.line(cx - radius + 1, cy + radius, cx + radius, cy - radius + 1, p3, 1)
                canvas.line(cx - radius, cy + radius // 2, cx - radius // 2, cy + radius, p2, 2)
            elif any(word in lower for word in ("armor", "shield", "guard")):
                canvas.ellipse(cx, cy, radius, radius, dark)
                canvas.ellipse(cx, cy, max(1, radius - 2), max(1, radius - 2), p1)
                canvas.line(cx, cy - radius + 2, cx, cy + radius - 2, p3)
            elif any(word in lower for word in ("item", "potion", "bottle", "medicine")):
                canvas.rect(cx - radius // 2, cy - radius, cx + radius // 2, cy - radius // 2, p2)
                canvas.ellipse(cx, cy + radius // 3, radius, radius, dark)
                canvas.ellipse(cx, cy + radius // 3, max(1, radius - 2), max(1, radius - 2), p1)
            elif local % 4 == 0:
                canvas.ellipse(cx, cy, radius, radius, dark)
                canvas.ellipse(cx, cy, max(1, radius - 2), max(1, radius - 2), p1)
            elif local % 4 == 1:
                canvas.triangle(((cx, cy - radius), (cx + radius, cy + radius), (cx - radius, cy + radius)), p2)
            elif local % 4 == 2:
                canvas.line(cx - radius, cy + radius, cx + radius, cy - radius, dark, max(2, radius // 3))
                canvas.line(cx - radius + 1, cy + radius, cx + radius, cy - radius + 1, p3, 1)
            else:
                canvas.rect(cx - radius, cy - radius, cx + radius, cy + radius, dark)
                canvas.rect(cx - radius + 2, cy - radius + 2, cx + radius - 2, cy + radius - 2, p0)
            if not atlas:
                return


def _draw_ui(canvas: Raster, name: str, palette, seed: int):
    p0, p1, p2, p3, dark = palette
    canvas.rect(0, 0, canvas.width - 1, canvas.height - 1, dark)
    border = max(2, min(canvas.width, canvas.height) // 16)
    canvas.rect(border, border, canvas.width - border - 1, canvas.height - border - 1, p0)
    canvas.rect(border * 2, border * 2, canvas.width - border * 2 - 1, canvas.height - border * 2 - 1, shade(p0, -20))
    for x in range(border, canvas.width - border, max(3, border * 2)):
        canvas.rect(x, 0, min(canvas.width - 1, x + border - 1), border - 1, p2)
        canvas.rect(x, canvas.height - border, min(canvas.width - 1, x + border - 1), canvas.height - 1, p2)
    for y in range(border, canvas.height - border, max(3, border * 2)):
        canvas.rect(0, y, border - 1, min(canvas.height - 1, y + border - 1), p3)
        canvas.rect(canvas.width - border, y, canvas.width - 1, min(canvas.height - 1, y + border - 1), p3)


def _draw_mask(canvas: Raster, name: str, palette, seed: int):
    white, gray, dark = (255, 255, 255, 255), (145, 145, 145, 255), (0, 0, 0, 255)
    canvas.rect(0, 0, canvas.width - 1, canvas.height - 1, dark)
    if "slash" in name.lower():
        canvas.line(0, canvas.height - 1, canvas.width - 1, 0, white, max(2, canvas.width // 8))
        canvas.line(0, canvas.height - 1, canvas.width - 1, 0, gray, max(1, canvas.width // 16))
    else:
        canvas.ellipse(canvas.width // 2, canvas.height // 2, canvas.width // 2 - 1, canvas.height // 2 - 1, gray)
        canvas.ellipse(canvas.width // 2, canvas.height // 2, canvas.width // 3, canvas.height // 3, white)


def render_visual(engine: str, path: str, policy: VisualPolicy) -> bytes:
    name = semantic_stem(path)
    seed = seed_int(f"visual:{name}:{policy.family}")
    palette = palette_for(name)
    canvas = Raster(policy.width, policy.height)
    if policy.family in ("scene", "overlay"):
        _draw_scene(canvas, name, palette, seed)
        if policy.family == "overlay":
            for y in range(canvas.height):
                for x in range(canvas.width):
                    if (x + y + seed) % 7:
                        canvas.pixel(x, y, (0, 0, 0, 0))
    elif policy.family in ("charset", "charset-xp", "charset-vx", "charset-vx-single"):
        _draw_charset(canvas, name, policy, palette, seed)
    elif policy.family in ("faces", "faces-vx", "portrait"):
        _draw_faces(canvas, name, policy, palette, seed)
    elif policy.family == "creature":
        _draw_creature(canvas, name, palette, seed)
    elif policy.family == "effect":
        _draw_effect(canvas, name, palette, seed)
    elif policy.family in ("tiles", "autotile"):
        _draw_tiles(canvas, name, palette, seed, 16 if policy.family == "autotile" or engine in ("rm2000", "rm2003", "wolf") else 32)
    elif policy.family == "fog":
        for index in range(18):
            x = (seed + index * 83) % canvas.width
            y = (seed // 3 + index * 47) % canvas.height
            canvas.ellipse(x, y, canvas.width // 5, canvas.height // 12, (*palette[3][:3], 96))
    elif policy.family in ("icon", "icon-atlas"):
        _draw_icon(canvas, name, palette, seed, policy.family == "icon-atlas")
    elif policy.family == "ui":
        _draw_ui(canvas, name, palette, seed)
    elif policy.family in ("mask", "transition"):
        _draw_mask(canvas, name, palette, seed)
    elif policy.family == "battle-character":
        fw, fh = 48, 48
        for row in range(8):
            for col in range(3):
                _draw_character(canvas, col * fw, row * fh, fw, fh, palette_for(f"{name}:{row}"), seed + row, row % 4, col)
    elif policy.family == "weapon-sheet":
        fw, fh = 64, 64
        for row in range(8):
            for col in range(3):
                ox, oy = col * fw, row * fh
                canvas.line(ox + 12, oy + 52, ox + 52, oy + 12, palette[4], 5)
                canvas.line(ox + 14, oy + 50, ox + 50, oy + 14, palette[(row + col) % 4], 2)
                canvas.line(ox + 20, oy + 48, ox + 30, oy + 58, palette[2], 3)
    else:
        raise ValueError(f"Unsupported visual family {policy.family}")
    return bytes(canvas.pixels)


def _quantize(rgba_bytes: bytes, palette):
    colors = [(0, 0, 0, 0)] + [tuple(color) for color in palette]
    colors += [shade(color, delta) for color in palette for delta in (-32, -16, 16, 32)]
    unique = []
    for color in colors:
        if color not in unique:
            unique.append(color)
    out = bytearray(len(rgba_bytes))
    cache = {}
    for offset in range(0, len(rgba_bytes), 4):
        pixel = tuple(rgba_bytes[offset:offset + 4])
        if pixel[3] < 128:
            chosen = (0, 0, 0, 0)
        else:
            key = pixel[:3]
            chosen = cache.get(key)
            if chosen is None:
                chosen = min(unique[1:], key=lambda color: sum((color[i] - key[i]) ** 2 for i in range(3)))
                cache[key] = chosen
        out[offset:offset + 4] = bytes(chosen)
    return bytes(out)


def _jpeg_from_png(png: bytes) -> bytes:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-vcodec", "png", "-i", "pipe:0",
        "-frames:v", "1", "-vf", "format=yuvj444p", "-c:v", "mjpeg", "-q:v", "4", "-fflags", "+bitexact",
        "-flags:v", "+bitexact", "-map_metadata", "-1", "-f", "image2pipe", "pipe:1",
    ]
    result = subprocess.run(command, input=png, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0 or not result.stdout.startswith(b"\xff\xd8\xff"):
        raise RuntimeError(f"ffmpeg JPEG encoding failed: {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout


def _ico_from_png(png: bytes, width: int, height: int) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0 if width == 256 else width, 0 if height == 256 else height, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def encode_visual(engine: str, path: str, policy: VisualPolicy, rgba_bytes: bytes, prequantized: bool = False) -> bytes:
    """`prequantized`: the RGBA already has binary alpha and at most 255 colours (structured FLUX assets)."""
    extension = os.path.splitext(path)[1].lower()
    if policy.indexed:
        if not prequantized:
            rgba_bytes = _quantize(rgba_bytes, palette_for(semantic_stem(path)))
        png = transforms.transform_rgba_to_indexed_png(rgba_bytes, policy.width, policy.height)
    else:
        from png_utils import create_rgba_png
        png = create_rgba_png(policy.width, policy.height, rgba_bytes)
    if extension == ".png":
        return png
    if extension == ".jpg":
        return _jpeg_from_png(png)
    if extension == ".ico":
        return _ico_from_png(png, policy.width, policy.height)
    raise ValueError(f"Unsupported visual extension: {extension}")
