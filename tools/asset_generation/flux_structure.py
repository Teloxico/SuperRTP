#!/usr/bin/env python3
"""
Turns FLUX.2 concepts (tools/asset_generation/flux_worker.py) into exact engine assets.

FLUX draws the art; everything an engine depends on is enforced here by deterministic
code: target dimensions, frame grids and their row/column semantics (shared with
tools/transforms.py), binary alpha, and at most 255 colours plus transparency for the
indexed RM2000/2003 formats.

    .cache/flux/venv/bin/python tools/asset_generation/flux_structure.py [--family F]

For every render key of the full-inventory plan whose concepts are all generated, it
writes .cache/flux/structured/<creative_id>/<family>-<w>x<h>.rgba (raw RGBA) plus a
.json sidecar binding the concept hashes and ALGORITHM_VERSION. The standard-library
full-inventory generator then encodes these instead of procedural art and records the
source of every entry in its manifest.

Known limits, recorded in docs/asset-generation.md: walking steps are synthesised from
one standing view per direction (a small leg offset), the right-facing view mirrors the
left one, battle poses are transforms of one sprite, and tile sheets fill each cell with
generated material textures rather than hand-designed tile semantics.
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)

import transforms  # noqa: E402
from asset_generation import flux_jobs  # noqa: E402
from asset_generation import generate_full_inventory as inventory  # noqa: E402
from asset_generation.flux_worker import FLUX_DIR, _atomic_write, concept_paths, is_done  # noqa: E402

ALGORITHM_VERSION = 1
STRUCTURED_DIR = os.path.join(FLUX_DIR, "structured")
KEY_MARGIN = 50              # how far the key channels must exceed the others for a pixel to count as backdrop
RM2K_LAYOUT = transforms.SheetLayout("rm2k_8", transforms.CANONICAL_ROWS, transforms.CANONICAL_COLUMNS, 4, 2)
VX_SINGLE_LAYOUT = transforms.SheetLayout("vx_single", ("DOWN", "LEFT", "RIGHT", "UP"), ("STEP_LEFT", "IDLE", "STEP_RIGHT"))


# ---------------------------------------------------------------------------
# Image helpers (arrays are H x W x 4 uint8 RGBA)
# ---------------------------------------------------------------------------

def load_concept(job) -> np.ndarray:
    return np.array(Image.open(concept_paths(job)[0]).convert("RGBA"))


def _key_dominant(rgb: np.ndarray, key_rgb) -> np.ndarray:
    """Pixels whose colour is dominated by the key's channels. FLUX casts soft shadows onto the
    key backdrop; those stay key-dominant (dark green or dark magenta), so they are keyed too."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if tuple(key_rgb) == (0, 255, 0):
        return (g > r + KEY_MARGIN) & (g > b + KEY_MARGIN)
    return (r > g + KEY_MARGIN) & (b > g + KEY_MARGIN) & (np.abs(r - b) < 90)


def key_out(img: np.ndarray, key_rgb) -> np.ndarray:
    """Removes the key background connected to the border and neutralises key-colour spill."""
    rgb = img[..., :3].astype(np.int32)
    near = _key_dominant(rgb, key_rgb)
    labels, _ = ndimage.label(near)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    background = np.isin(labels, border[border > 0])
    # Backdrop seen through enclosed gaps (between fingers, inside a coiled tail) is not
    # connected to the border; nearly pure key colour is removed wherever it appears.
    background |= np.sqrt(((rgb - np.array(key_rgb)) ** 2).sum(axis=2)) < 60
    out = img.copy()
    out[background] = 0
    edge = ndimage.binary_dilation(background, iterations=3) & ~background
    k = np.array(key_rgb)
    if k[1] == 255 and k[0] == 0:        # green key: cap green at the brighter of red and blue
        g_cap = np.maximum(rgb[..., 0], rgb[..., 2])
        out[..., 1] = np.where(edge, np.minimum(rgb[..., 1], g_cap), out[..., 1])
    else:                                # magenta key: cap red and blue at green
        for c in (0, 2):
            out[..., c] = np.where(edge, np.minimum(rgb[..., c], rgb[..., 1]), out[..., c])
    return out


def bbox(img: np.ndarray):
    ys, xs = np.nonzero(img[..., 3] > 0)
    if len(xs) == 0:
        raise ValueError("Concept has no foreground after keying")
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def crop_to_content(img: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = bbox(img)
    return img[y0:y1, x0:x1]


def resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Area-averaged downscale with premultiplied alpha, then binary alpha."""
    arr = img.astype(np.float32) / 255.0
    arr[..., :3] *= arr[..., 3:4]
    channels = [np.array(Image.fromarray(arr[..., c]).resize((w, h), Image.Resampling.BOX)) for c in range(4)]
    out = np.stack(channels, axis=2)
    alpha = out[..., 3:4]
    rgb = np.where(alpha > 1e-4, out[..., :3] / np.maximum(alpha, 1e-4), 0)
    result = np.concatenate([rgb, (alpha >= 0.5).astype(np.float32)], axis=2)
    result = np.clip(np.round(result * 255), 0, 255).astype(np.uint8)
    result[result[..., 3] == 0] = 0
    return result


def fit(sprite: np.ndarray, w: int, h: int, margin: int = 1, anchor: str = "bottom") -> np.ndarray:
    """Scales a cropped sprite into a w x h transparent frame, keeping its aspect ratio."""
    sh, sw = sprite.shape[:2]
    scale = min((w - 2 * margin) / sw, (h - 2 * margin) / sh)
    tw, th = max(1, round(sw * scale)), max(1, round(sh * scale))
    small = resize(sprite, tw, th)
    frame = np.zeros((h, w, 4), np.uint8)
    x = (w - tw) // 2
    y = h - margin - th if anchor == "bottom" else (h - th) // 2
    frame[y:y + th, x:x + tw] = small
    return frame


def cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Centre-crops an opaque image to the w:h aspect ratio and scales it to w x h."""
    ih, iw = img.shape[:2]
    if iw / ih > w / h:
        cw = round(ih * w / h)
        img = img[:, (iw - cw) // 2:(iw - cw) // 2 + cw]
    else:
        ch = round(iw * h / w)
        img = img[(ih - ch) // 2:(ih - ch) // 2 + ch]
    return np.array(Image.fromarray(img).resize((w, h), Image.Resampling.LANCZOS))


def split_views(img: np.ndarray, count: int = 3) -> tuple:
    """Splits a keyed turnaround into `count` views by empty columns; falls back to equal thirds."""
    occupied = (img[..., 3] > 0).any(axis=0)
    runs, start = [], None
    for x, on in enumerate(list(occupied) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append((start, x))
            start = None
    runs = sorted(sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:count])
    if len(runs) == count and min(r[1] - r[0] for r in runs) > img.shape[1] // 20:
        return [crop_to_content(img[:, a:b]) for a, b in runs], "column-gaps"
    width = img.shape[1] // count
    return [crop_to_content(img[:, i * width:(i + 1) * width]) for i in range(count)], "equal-thirds"


def step_frame(frame: np.ndarray, side: str, profile: bool) -> np.ndarray:
    """A walking step from a standing frame: the lower third's legs offset by one pixel."""
    out = frame.copy()
    ys, xs = np.nonzero(frame[..., 3] > 0)
    if len(ys) == 0:
        return out
    y0, y1 = ys.min(), ys.max() + 1
    legs_top = y0 + (y1 - y0) * 2 // 3
    region = frame[legs_top:y1]
    if profile:                         # side view: stride shifts the legs horizontally
        out[legs_top:y1] = np.roll(region, -1 if side == "STEP_LEFT" else 1, axis=1)
    else:                               # front/back: one leg lifts
        cx = (xs.min() + xs.max()) // 2
        cols = slice(None, cx) if side == "STEP_LEFT" else slice(cx, None)
        lifted = np.zeros_like(region)
        lifted[:-1, cols] = region[1:, cols]
        lifted[:, :][:, (slice(cx, None) if side == "STEP_LEFT" else slice(None, cx))] = \
            region[:, (slice(cx, None) if side == "STEP_LEFT" else slice(None, cx))]
        out[legs_top:y1] = lifted
    return out


def walking_frames(concept: np.ndarray, frame_w: int, frame_h: int) -> tuple:
    """frames[direction][phase] for one character from a keyed front/left/back turnaround."""
    (front, left, back), method = split_views(concept)
    views = {"DOWN": front, "LEFT": left, "RIGHT": left[:, ::-1], "UP": back}
    frames = {}
    for direction, view in views.items():
        idle = fit(view, frame_w, frame_h)
        profile = direction in ("LEFT", "RIGHT")
        frames[direction] = {"IDLE": idle, "STEP_LEFT": step_frame(idle, "STEP_LEFT", profile),
                             "STEP_RIGHT": step_frame(idle, "STEP_RIGHT", profile)}
    return frames, method


def to_bytes_frames(frames: dict) -> dict:
    return {d: {p: np.ascontiguousarray(f).tobytes() for p, f in phases.items()} for d, phases in frames.items()}


def grid(tiles: list, cols: int, tile_w: int, tile_h: int) -> np.ndarray:
    rows = (len(tiles) + cols - 1) // cols
    out = np.zeros((rows * tile_h, cols * tile_w, 4), np.uint8)
    for i, tile in enumerate(tiles):
        out[(i // cols) * tile_h:(i // cols + 1) * tile_h, (i % cols) * tile_w:(i % cols + 1) * tile_w] = tile
    return out


def quantize_indexed(img: np.ndarray, colors: int = 255) -> np.ndarray:
    """At most `colors` opaque colours plus fully transparent pixels (RM2000/2003 indexed PNG)."""
    opaque = img[..., 3] > 0
    rgb = Image.fromarray(np.where(opaque[..., None], img[..., :3], 0).astype(np.uint8), "RGB")
    pal = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    out = np.zeros_like(img)
    out[..., :3] = np.array(pal)
    out[..., 3] = np.where(opaque, 255, 0)
    out[~opaque] = 0
    return out


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def _keyed_concepts(jobs) -> list:
    return [key_out(load_concept(job), job.key_rgb) if job.key_rgb else load_concept(job) for job in jobs]


def build(family: str, width: int, height: int, jobs: list) -> tuple:
    """Returns (H x W x 4 array, notes) for one render key from its generated concepts."""
    notes = {}
    concepts = _keyed_concepts(jobs)
    if family == "creature":
        out = fit(crop_to_content(concepts[0]), width, height, margin=2)
    elif family == "icon":
        out = fit(crop_to_content(concepts[0]), width, height, margin=1, anchor="center")
    elif family in ("charset", "charset-vx", "charset-xp", "charset-vx-single"):
        layout = {"charset": RM2K_LAYOUT, "charset-vx": transforms.VX_FAMILY_LAYOUT,
                  "charset-xp": transforms.RMXP_LAYOUT, "charset-vx-single": VX_SINGLE_LAYOUT}[family]
        frame_w = width // (layout.characters_across * len(layout.columns))
        frame_h = height // (layout.characters_down * len(layout.rows))
        characters, methods = [], []
        for concept in concepts:
            frames, method = walking_frames(concept, frame_w, frame_h)
            characters.append(to_bytes_frames(frames))
            methods.append(method)
        notes["view_split"] = methods
        out = np.frombuffer(transforms.pack_sheet_rgba(characters, layout, frame_w, frame_h), np.uint8).reshape(height, width, 4)
    elif family == "battle-character":
        size = width // 3
        base = fit(crop_to_content(concepts[0]), size, size, margin=2)
        rows = []
        for row in range(height // size):
            for col in range(3):
                frame = base.copy()
                if row == 1:        # attack lunge
                    frame = np.roll(frame, -2 * (col + 1), axis=1)
                elif row == 4:      # knocked out: lying down
                    frame = fit(crop_to_content(np.rot90(base).copy()), size, size, margin=2)
                elif row == 5:      # hurt: recoil and red tint
                    frame = np.roll(frame, 2, axis=1)
                    frame[..., 0] = np.where(frame[..., 3] > 0, np.minimum(255, frame[..., 0].astype(int) + 60), 0)
                elif row == 6:      # weakened: darker
                    frame[..., :3] = (frame[..., :3] * 0.6).astype(np.uint8)
                else:               # idle breathing
                    frame = np.roll(frame, -(col % 2), axis=0)
                rows.append(frame)
        out = grid(rows, 3, size, size)
    elif family in ("faces", "faces-vx", "portrait"):
        cols = {"faces": 4, "faces-vx": 4, "portrait": 1}[family]
        rows_n = len(concepts) // cols
        cell_w, cell_h = width // cols, height // rows_n
        cells = []
        for concept in concepts:
            x0, y0, x1, y1 = bbox(concept)
            side = min(x1 - x0, concept.shape[0] - y0)
            cx = (x0 + x1) // 2
            head = concept[y0:y0 + side, max(0, cx - side // 2):max(0, cx - side // 2) + side]
            cells.append(fit(crop_to_content(head), cell_w, cell_h, margin=0, anchor="center"))
        out = grid(cells, cols, cell_w, cell_h)
    elif family in ("scene", "overlay", "fog"):
        rgb = cover(concepts[0][..., :3].copy(), width, height)
        alpha = np.full((height, width), 255, np.uint8)
        if family == "fog":
            alpha = rgb.max(axis=2)
        elif family == "overlay":
            yy, xx = np.mgrid[0:height, 0:width]
            dist = np.sqrt(((xx - width / 2) / (width / 2)) ** 2 + ((yy - height / 2) / (height / 2)) ** 2)
            alpha = np.where(dist > 0.85, 255, 0).astype(np.uint8)
        out = np.dstack([rgb, alpha])
    elif family == "transition":
        gray = cover(concepts[0][..., :3].copy(), width, height).mean(axis=2).astype(np.uint8)
        out = np.dstack([gray, gray, gray, np.full_like(gray, 255)])
    elif family == "effect":
        frames_across = 5
        size = width // frames_across
        src = concepts[0][..., :3].astype(np.float32)
        glow = src.max(axis=2)
        effect = np.dstack([src, glow]).astype(np.uint8)
        effect[glow < 24] = 0
        base = crop_to_content(effect)
        cells = []
        for i in range(frames_across * (height // size)):
            t = (i + 1) / (frames_across * (height // size))
            scale = 0.35 + 0.65 * min(1.0, t * 1.6)   # grows to exactly the cell size, never beyond
            inner = max(4, round(size * scale))
            frame = np.zeros((size, size, 4), np.uint8)
            piece = fit(base, inner, inner, margin=0, anchor="center")
            if t > 0.7:        # fade out over the last third
                piece[..., 3] = (piece[..., 3] * max(0.0, (1 - t) / 0.3)).astype(np.uint8)
                piece[piece[..., 3] < 128] = 0
                piece[..., 3] = np.where(piece[..., 3] > 0, 255, 0)
            off = (size - inner) // 2
            frame[off:off + inner, off:off + inner] = piece
            cells.append(frame)
        out = grid(cells, frames_across, size, size)
    elif family in ("tiles", "autotile"):
        tile = 32 if width >= 256 and height >= 512 and family == "tiles" and width % 32 == 0 and width != 480 else 16
        textures = [cover(c[..., :3].copy(), 128, 128) for c in concepts]
        cols, rows = width // tile, height // tile
        out = np.zeros((height, width, 4), np.uint8)
        for r in range(rows):
            for c in range(cols):
                tex = textures[((r // 2) + (c // 4)) % len(textures)]
                ox, oy = (c * 37) % (128 - tile), (r * 53) % (128 - tile)
                cell = tex[oy:oy + tile, ox:ox + tile]
                if family == "autotile":   # darker rim on the outer ring of the autotile block
                    cell = cell.copy()
                    if r in (0, rows - 1) or c in (0, cols - 1):
                        cell = (cell * 0.75).astype(np.uint8)
                out[r * tile:(r + 1) * tile, c * tile:(c + 1) * tile, :3] = cell
                out[r * tile:(r + 1) * tile, c * tile:(c + 1) * tile, 3] = 255
        notes["tile_size"] = tile
    else:
        raise ValueError(f"No FLUX structuring for family {family}")
    if out.shape != (height, width, 4):
        raise ValueError(f"{family}: built {out.shape[1]}x{out.shape[0]}, expected {width}x{height}")
    return out, notes


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def structured_paths(creative_id: str, family: str, width: int, height: int) -> tuple:
    base = os.path.join(STRUCTURED_DIR, creative_id, f"{family}-{width}x{height}")
    return base + ".rgba", base + ".json"


def concept_binding(jobs) -> list:
    out = []
    for job in jobs:
        with open(concept_paths(job)[1], encoding="utf-8") as f:
            out.append({"job_id": job.job_id, "image_sha256": json.load(f)["image_sha256"]})
    return out


def structure_all(only_families=None) -> dict:
    plan = inventory.build_plan(inventory.load_spec())
    counts = {"written": 0, "current": 0, "waiting_for_concepts": 0, "procedural_family": 0, "failed": 0}
    seen = set()
    for entry in plan:
        if entry["media"] != "visual" or entry["alias_of"]:
            continue
        d = entry["details"]
        key = (entry["creative_id"], entry["family"], d["width"], d["height"], d["indexed"])
        if key in seen or (only_families and entry["family"] not in only_families):
            continue
        seen.add(key)
        jobs = flux_jobs.jobs_for(entry["creative_id"], entry["family"], d["width"], d["height"])
        if not jobs:
            counts["procedural_family"] += 1
            continue
        if not all(is_done(job) for job in jobs):
            counts["waiting_for_concepts"] += 1
            continue
        rgba_path, sidecar_path = structured_paths(entry["creative_id"], entry["family"], d["width"], d["height"])
        binding = concept_binding(jobs)
        stamp = {"algorithm_version": ALGORITHM_VERSION, "indexed": d["indexed"], "concepts": binding}
        if os.path.exists(sidecar_path):
            with open(sidecar_path, encoding="utf-8") as f:
                existing = json.load(f)
            if {k: existing.get(k) for k in stamp} == stamp:
                counts["current"] += 1
                continue
        try:
            img, notes = build(entry["family"], d["width"], d["height"], jobs)
            if d["indexed"]:
                img = quantize_indexed(img)
        except Exception as exc:
            counts["failed"] += 1
            print(f"FAILED {entry['creative_id']} ({entry['family']}): {exc!r}", file=sys.stderr, flush=True)
            continue
        data = np.ascontiguousarray(img).tobytes()
        record = dict(stamp, source="flux2-klein-4b", family=entry["family"], width=d["width"], height=d["height"],
                      rgba_sha256=hashlib.sha256(data).hexdigest(), notes=notes)
        # Atomic writes: the worker structures in-process while a manual run may be reading.
        _atomic_write(rgba_path, data)
        _atomic_write(sidecar_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
        counts["written"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description="Structure generated FLUX concepts into exact engine assets")
    parser.add_argument("--family", action="append")
    args = parser.parse_args()
    counts = structure_all(args.family)
    print(json.dumps(counts, indent=2))
    sys.exit(1 if counts["failed"] else 0)


if __name__ == "__main__":
    main()
