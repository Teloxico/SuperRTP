#!/usr/bin/env python3
"""
WOLF RPG Editor 3.717 CharaChip runtime verification through the official Game.exe.

Fixture tests/fixtures/wolf_character_min is a WOLF project whose SampleMap.mps holds
seven map events using CharaChip/SuperRTP_Calibration.png at 2x zoom on a black map:
  - top row (y=64):     idle DOWN, LEFT, RIGHT, UP   (patterns 2, 5, 8, 11)
  - bottom row (y=192): DOWN step-left, idle, step-right (patterns 1, 2, 3)
Common event 0 asks the engine for the image size (<<GET_IMAGE_SIZE>>) and prints
"RESULT:<w>" / "<h>" at the bottom left, which is read back from the pixels.

Pattern numbers count cells left to right, top to bottom (1..12) in the 3x4 CharaChip
(docs/engine-facts.md). Directional captures rewrite event 0 of the map to show one
pattern at (280, 160). The negative control omits the CharaChip file and must show
WOLF's green LoadGraphic error banner and write Game_ErrorLog.txt.

Usage:
  python3 tools/verify_wolf_runtime.py --verify
  python3 tools/verify_wolf_runtime.py --run-capture [--artifacts-dir DIR]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wolf_runtime as wolf
from build_target import build_target
from evidence import check_file_hash, check_timestamp, expect_field, load_evidence, require, write_evidence
from generate_calibration_charset import SLOT_THEMES
from png_utils import decode_png_rgb, read_png
from registry import find_asset, load_slot_mapping
from repo import evidence_timestamp, load_json, repo_path, sha256_file
from wolf_map_utils import compress_mps, decompress_mps, dump_mps_body, parse_mps_body

# Kept importable for callers of the previous module layout.
PINNED_WOLF_VERSION = wolf.PINNED_WOLF_VERSION
PINNED_WOLF_TAG = wolf.PINNED_WOLF_TAG
PINNED_WOLF_COMMIT = wolf.PINNED_WOLF_COMMIT
PINNED_ARCHIVE_SHA256 = wolf.PINNED_ARCHIVE_SHA256
PINNED_GAME_EXE_SHA256 = wolf.PINNED_GAME_EXE_SHA256

SLOT = "Data/CharaChip/SuperRTP_Calibration.png"
RUNTIME_REFERENCE = "CharaChip/SuperRTP_Calibration.png"
CANONICAL_ASSET_ID = "test.calibration.walking-character"
EXPECTED_LOOKUP = "72 128"
ERROR_LOG_ENTRY = f"ERROR: Cannot find [{RUNTIME_REFERENCE}]"
BLACK = (0, 0, 0)
ZOOM = 2
TOLERANCE = 4  # per-channel difference allowed for opaque pixels after WOLF's scaling

# (name, screen x, screen y, pattern) of the seven events in the positive composite.
COMPOSITE_SLOTS = [
    ("down_idle", 120, 64, 2), ("left_idle", 216, 64, 5), ("right_idle", 312, 64, 8), ("up_idle", 408, 64, 11),
    ("step_left", 184, 192, 1), ("idle_walk", 280, 192, 2), ("step_right", 376, 192, 3),
]

# Directional captures: file -> (event direction code, event frame index, expected pattern, description).
DIRECTIONAL_SHOTS = {
    "wolf_character_down.png": (2, 1, 2, "Down Idle"),
    "wolf_character_left.png": (4, 1, 5, "Left Idle"),
    "wolf_character_right.png": (6, 1, 8, "Right Idle"),
    "wolf_character_up.png": (8, 1, 11, "Up Idle"),
    "wolf_character_walk_step1.png": (2, 0, 1, "Down Step Left"),
    "wolf_character_walk_step2.png": (2, 2, 3, "Down Step Right"),
}
DIRECTIONAL_ORIGIN = (280, 160)
DIRECTIONAL_EVENT_CELL = (9, 6)
DIRECTIONAL_SEARCH = [DIRECTIONAL_ORIGIN] + [(x, y) for _, x, y, _ in COMPOSITE_SLOTS] + [(70, 60)]

# Glyph bitmaps of the digits in "72 128" as Wine renders the fixture's text with only its
# bundled fonts visible (wolf_runtime.FONTCONFIG_FILE; threshold 80 on the red channel).
# Only these four digits occur; any other glyph decodes as '?'.
REF_DIGITS = {
    "7": ["11111111111", "11111111111", "11111111111", "00000000110", "00000001110", "00000001110", "00000001100", "00000011100", "00000011000", "00000111000", "00000111000", "00000110000", "00001110000", "00001100000", "00011100000", "00011100000", "00011000000", "00111000000"],
    "2": ["00111111000", "11111111100", "11100001110", "00000000111", "00000000111", "00000000011", "00000000111", "00000000110", "00000001110", "00000011100", "00000111000", "00001110000", "00011100000", "00111000000", "01110000000", "11100000000", "11111111111", "11111111111"],
    "1": ["001110000", "111111000", "111111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "000111000", "111111111", "111111111"],
    "8": ["000111111000", "001111111100", "011100001110", "011000001110", "111000000110", "011000000110", "011100001110", "001111111100", "000111111000", "001111111100", "011100001110", "111000000110", "111000000111", "111000000110", "111000000110", "011000001110", "011110111100", "000111111000"],
}
GLYPH_MAX_DIFF = 4
TEXT_THRESHOLD = 80
LOOKUP_LINES = ((384, 402), (418, 438))  # y ranges of "RESULT:<w>" and "<h>"
LOOKUP_X = (20, 160)


def get_target_config(artifacts_dir=None):
    slot = load_slot_mapping("wolf")["slots"][SLOT]
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", "wolf", "character")
    return {
        "target": "wolf",
        "engine": "WOLF RPG Editor",
        "runtime": "official WOLF Game.exe",
        "runtime_version": wolf.PINNED_WOLF_VERSION,
        "release_tag": wolf.PINNED_WOLF_TAG,
        "release_commit": wolf.PINNED_WOLF_COMMIT,
        "runtime_archive_sha256": wolf.PINNED_ARCHIVE_SHA256,
        "game_exe_sha256": wolf.PINNED_GAME_EXE_SHA256,
        "category": slot["category"],
        "wolf_resource_class": "CharaChip",
        "expected_character_slot": os.path.basename(SLOT),
        "runtime_reference": slot["runtime_reference"],
        "direction_mode": slot["direction_mode"],
        "animation_patterns": slot["animation_patterns"],
        "canonical_asset_id": slot["asset_id"],
        "canonical_asset_sha256": find_asset(slot["asset_id"])[1]["sha256"],
        "source_character_index": slot["character_index"],
        "transform_policy": slot["transform_policy"],
        "fixture_dir": repo_path("tests", "fixtures", "wolf_character_min"),
        "target_dir": repo_path("generated", "wolf"),
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
    }


# ---------------------------------------------------------------------------
# Reading the rendered lookup result
# ---------------------------------------------------------------------------

def _glyph_bitmap(pixels, y1, y2, x1, x2):
    lit = [(x, y) for y in range(y1, y2) for x in range(x1, x2) if pixels[y][x][0] > TEXT_THRESHOLD]
    if not lit:
        return []
    min_x, max_x = min(x for x, _ in lit), max(x for x, _ in lit)
    min_y, max_y = min(y for _, y in lit), max(y for _, y in lit)
    return ["".join("1" if pixels[y][x][0] > TEXT_THRESHOLD else "0" for x in range(min_x, max_x + 1))
            for y in range(min_y, max_y + 1)]


def match_digit_bitmap(bitmap):
    """Returns the reference digit within GLYPH_MAX_DIFF differing pixels of `bitmap`, else '?'."""
    if not bitmap:
        return "?"
    best, best_diff = "?", None
    for digit, ref in REF_DIGITS.items():
        h, w = max(len(bitmap), len(ref)), max(len(bitmap[0]), len(ref[0]))
        diff = sum(1 for y in range(h) for x in range(w)
                   if (bitmap[y][x] if y < len(bitmap) and x < len(bitmap[0]) else "0")
                   != (ref[y][x] if y < len(ref) and x < len(ref[0]) else "0"))
        if best_diff is None or diff < best_diff:
            best, best_diff = digit, diff
    return best if best_diff <= GLYPH_MAX_DIFF else "?"


def _glyph_spans(pixels, y1, y2, x1, x2):
    columns = [any(pixels[y][x][0] > TEXT_THRESHOLD for y in range(y1, y2)) for x in range(x1, x2)]
    spans, start = [], None
    for i, lit in enumerate(columns + [False]):
        if lit and start is None:
            start = x1 + i
        elif not lit and start is not None:
            spans.append((start, x1 + i))
            start = None
    return spans


def _is_colon(bitmap) -> bool:
    """A narrow glyph made of two blobs separated by at least one blank row."""
    return bool(bitmap) and len(bitmap[0]) <= 4 and any("1" not in row for row in bitmap)


def decode_lookup_dimensions(pixels):
    """Reads '<w> <h>' from the RESULT lines the fixture prints, or 'UNKNOWN'."""
    (a1, a2), (b1, b2) = LOOKUP_LINES
    line1 = _glyph_spans(pixels, a1, a2, *LOOKUP_X)
    line2 = _glyph_spans(pixels, b1, b2, *LOOKUP_X)
    # The width follows "RESULT:". Letters can touch and share a span, so the prefix is
    # located by its colon rather than by counting glyphs.
    colons = [i for i, (x1, x2) in enumerate(line1) if _is_colon(_glyph_bitmap(pixels, a1, a2, x1, x2))]
    if not colons or colons[-1] == len(line1) - 1 or not line2:
        return "UNKNOWN"
    width = "".join(match_digit_bitmap(_glyph_bitmap(pixels, a1, a2, x1, x2)) for x1, x2 in line1[colons[-1] + 1:])
    height = "".join(match_digit_bitmap(_glyph_bitmap(pixels, b1, b2, x1, x2)) for x1, x2 in line2)
    return f"{width} {height}"


# ---------------------------------------------------------------------------
# Screenshot checks
# ---------------------------------------------------------------------------

def _cells(target_char_path):
    """pattern number (1..12) -> 32 rows of 24 (r, g, b, a) tuples from the target CharaChip."""
    sheet = read_png(target_char_path)
    if (sheet.width, sheet.height) != (72, 128):
        raise ValueError(f"Expected 72x128 target character, got {sheet.width}x{sheet.height}")
    rgba = sheet.rgba_bytes()
    cells = {}
    for row in range(4):
        for col in range(3):
            cells[row * 3 + col + 1] = [[tuple(rgba[o:o + 4]) for o in (((row * 32 + cy) * 72 + col * 24 + cx) * 4 for cx in range(24))]
                                        for cy in range(32)]
    return cells


def _check_cell(pixels, cell, sx, sy, name):
    for cy in range(32):
        for cx in range(24):
            screen = pixels[sy + cy * ZOOM][sx + cx * ZOOM]
            r, g, b, a = cell[cy][cx]
            if a == 255:
                diff = max(abs(screen[0] - r), abs(screen[1] - g), abs(screen[2] - b))
                if diff > TOLERANCE:
                    raise ValueError(f"Pixel mismatch in {name} at cell ({cx}, {cy}): expected {(r, g, b)}, got {screen} (diff={diff})")
            elif a == 0 and screen != BLACK:
                raise ValueError(f"Transparent pixel did not expose black background in {name} at cell ({cx}, {cy}): got {screen}")


def _cell_matches_sample(pixels, cell, sx, sy):
    for cy in (5, 10, 15, 20):
        for cx in (5, 10, 15):
            screen = pixels[sy + cy * ZOOM][sx + cx * ZOOM]
            r, g, b, a = cell[cy][cx]
            if a == 255 and max(abs(screen[0] - r), abs(screen[1] - g), abs(screen[2] - b)) > TOLERANCE:
                return False
            if a == 0 and screen != BLACK:
                return False
    return True


def _check_semantics(cells):
    """Independent of the screen: arrows point the right way and step frames move the feet."""
    body, foot = SLOT_THEMES[0]["body"], SLOT_THEMES[0]["foot"]

    def points(pattern, color):
        return [(x, y) for y in range(32) for x in range(24) if cells[pattern][y][x][3] == 255 and cells[pattern][y][x][:3] == color]

    down_tip = max(y for _, y in points(2, body))
    up_tip = min(y for _, y in points(11, body))
    left_tip = min(x for x, _ in points(5, body))
    right_tip = max(x for x, _ in points(8, body))
    if not (down_tip > 18 and up_tip < 8):
        raise ValueError(f"Directional assertion failed: Down tip y={down_tip}, Up tip y={up_tip}")
    if not (left_tip < 6 and right_tip > 17):
        raise ValueError(f"Directional assertion failed: Left tip x={left_tip}, Right tip x={right_tip}")
    if points(1, foot) == points(2, foot) or points(3, foot) == points(2, foot):
        raise ValueError("Movement animation assertion failed: step foot positions equal idle foot positions")


def _verify_negative(pixels):
    green_bar = text = 0
    for y in range(192, 288):
        for r, g, b in pixels[y]:
            if r == 0 and 35 <= g <= 60 and b == 0:
                green_bar += 1
            elif (g > 60 and g >= r and g >= b) or (r > 120 and g > 120 and b > 120):
                text += 1
    if green_bar < 50000:
        raise ValueError(f"Negative control missing green error banner: only {green_bar} green bar pixels found")
    if text < 200:
        raise ValueError(f"Negative control missing error text in banner: only {text} text pixels found")
    for y in range(180):
        for x, px in enumerate(pixels[y]):
            if px != BLACK:
                raise ValueError(f"Unexpected non-black pixel outside negative banner at ({x}, {y}): {px}")
    return {"status": "NEGATIVE_CONTROL_VERIFIED", "green_bar_pixels": green_bar, "text_pixels": text, "banner_bbox": [0, 192, 640, 288]}


def verify_wolf_screenshot(shot_path, target_char_path=None, mode="positive", expected_pat=None):
    """
    Checks a 640x480 WOLF capture.
      mode='positive':         all seven composite events, the semantics, and the lookup text
      mode='directional':      one event showing `expected_pat` (found at a known position)
      mode='negative_control': the green error banner on an otherwise black screen
    """
    w, h, pixels = decode_png_rgb(shot_path)
    if (w, h) != (wolf.SCREEN_W, wolf.SCREEN_H):
        raise ValueError(f"Expected 640x480 screenshot, got {w}x{h}")
    if mode == "negative_control":
        return _verify_negative(pixels)
    if not target_char_path or not os.path.exists(target_char_path):
        raise FileNotFoundError(f"Target character path not found: {target_char_path}")
    cells = _cells(target_char_path)

    if mode == "positive":
        for x, y in [(10, 10), (625, 10), (310, 20), (10, 300), (625, 300)]:
            if pixels[y][x] != BLACK:
                raise ValueError(f"Expected black background at ({x}, {y}), got {pixels[y][x]}")
        for name, sx, sy, pattern in COMPOSITE_SLOTS:
            _check_cell(pixels, cells[pattern], sx, sy, name)
        _check_semantics(cells)
        lookup = decode_lookup_dimensions(pixels)
        if lookup != EXPECTED_LOOKUP:
            raise ValueError(f"Extracted lookup dimensions mismatch: expected '{EXPECTED_LOOKUP}', got '{lookup}'")
        return {"status": "POSITIVE_COMPOSITE_VERIFIED", "directions_verified": ["DOWN", "LEFT", "RIGHT", "UP"],
                "animation_phases_verified": ["STEP_LEFT", "IDLE", "STEP_RIGHT"], "extracted_lookup": lookup}

    if mode != "directional" or expected_pat is None:
        raise ValueError("mode must be 'positive', 'negative_control' or 'directional' (with expected_pat)")
    found = next((pos for pos in DIRECTIONAL_SEARCH if _cell_matches_sample(pixels, cells[expected_pat], *pos)), None)
    if not found:
        raise ValueError(f"Pattern {expected_pat} not found in directional screenshot {shot_path}")
    _check_cell(pixels, cells[expected_pat], *found, f"directional shot pattern {expected_pat}")
    return {"status": "DIRECTIONAL_SHOT_VERIFIED", "pattern": expected_pat, "position": list(found)}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def _diagnostic_from_error_log(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    match = re.search(r"ERROR: Cannot find \[[^\]]+\]", text)
    if not match:
        raise ValueError(f"Game_ErrorLog.txt does not contain a 'Cannot find' entry: {text.strip()[:300]}")
    return match.group(0)


def verify_evidence_chain(evidence_path=None, cfg=None, artifacts_dir=None):
    """Verifies WOLF evidence against the current files and re-inspects every screenshot."""
    cfg = cfg or get_target_config(artifacts_dir)
    ev = load_evidence(evidence_path or cfg["evidence_path"])
    artifacts_dir = cfg["artifacts_dir"]

    for field, label in (("target", "Evidence target"), ("engine", "Evidence engine"), ("runtime", "Evidence runtime"),
                         ("release_tag", "Evidence release tag"), ("category", "Evidence category"),
                         ("expected_character_slot", "Evidence character slot"),
                         ("runtime_version", "Evidence runtime version"), ("release_commit", "Evidence commit"),
                         ("runtime_archive_sha256", "Evidence archive SHA"), ("game_exe_sha256", "Evidence Game.exe SHA"),
                         ("wolf_resource_class", "Resource class"), ("runtime_reference", "Runtime reference"),
                         ("direction_mode", "Direction mode"), ("animation_patterns", "Animation patterns"),
                         ("canonical_asset_id", "Canonical asset id"), ("source_character_index", "Source character index"),
                         ("transform_policy", "Transform policy")):
        expect_field(ev, field, cfg[field], label)
    check_timestamp(ev, "timestamp")
    env = ev.get("runtime_environment_metadata")
    require(isinstance(env, dict) and bool(env.get("wine_version")), "Evidence runtime_environment_metadata must record the Wine version used")

    check_file_hash(repo_path("registry", "assets", "test_calibration_walking_character.rgba"), ev.get("canonical_asset_sha256"), "Canonical asset SHA")
    target_char = os.path.join(cfg["target_dir"], SLOT)
    check_file_hash(target_char, ev.get("target_png_sha256"), "Target character SHA")
    check_file_hash(os.path.join(cfg["target_dir"], "manifest.json"), ev.get("target_manifest_sha256"), "Target manifest SHA")

    fixture_manifest_path = os.path.join(cfg["fixture_dir"], "fixture_manifest.json")
    check_file_hash(fixture_manifest_path, ev.get("fixture_manifest_sha256"), "Fixture manifest SHA")
    manifest = load_json(fixture_manifest_path)
    for section, field in (("project_data", "fixture_project_data_hashes"), ("support_assets", "fixture_support_asset_hashes")):
        declared = {path: info["sha256"] for path, info in manifest[section].items()}
        require(ev.get(field) == declared, f"Evidence {field} does not match the fixture manifest")
        for rel, digest in declared.items():
            check_file_hash(os.path.join(cfg["fixture_dir"], rel), digest, f"Fixture file {rel} SHA")

    expect_field(ev, "positive_lookup_result", EXPECTED_LOOKUP, "Positive lookup result")
    for kind in ("positive", "negative"):
        check_file_hash(os.path.join(artifacts_dir, f"{kind}_runtime.log"), ev.get(f"{kind}_runtime_log_sha256"), f"{kind.capitalize()} runtime log hash")

    error_log = os.path.join(artifacts_dir, "Game_ErrorLog.txt")
    if not os.path.exists(error_log):
        raise FileNotFoundError(f"Negative runtime error log missing: {error_log} (Game_ErrorLog.txt)")
    check_file_hash(error_log, ev.get("negative_error_log_sha256"), "Game_ErrorLog.txt hash")
    with open(error_log, "rb") as f:
        diagnostic = _diagnostic_from_error_log(f.read())
    require(diagnostic == ERROR_LOG_ENTRY, f"Game_ErrorLog.txt names the wrong missing file: {diagnostic}")
    expect_field(ev, "negative_diagnostic", diagnostic, "Negative diagnostic")

    captures = {}
    shots = ev.get("positive_screenshots", {})
    require(set(shots) == {"wolf_character_positive.png"} | set(DIRECTIONAL_SHOTS),
            f"Evidence positive_screenshots must list the composite and all directional captures, got {sorted(shots)}")
    for name, digest in shots.items():
        path = os.path.join(artifacts_dir, name)
        check_file_hash(path, digest, f"Screenshot {name} SHA")
        if name == "wolf_character_positive.png":
            res = verify_wolf_screenshot(path, target_char_path=target_char, mode="positive")
            print(f"  [PASS] {name}: composite verified, lookup '{res['extracted_lookup']}'")
        else:
            pattern = DIRECTIONAL_SHOTS[name][2]
            res = verify_wolf_screenshot(path, target_char_path=target_char, mode="directional", expected_pat=pattern)
            captures[name] = {"pattern": res["pattern"], "position": res["position"]}
            print(f"  [PASS] {name}: pattern {pattern} at {tuple(res['position'])}")
    require(ev.get("directional_captures") == captures, "directional_captures does not match the re-inspected screenshots")
    negative = ev.get("negative_screenshot", {})
    require(list(negative) == ["wolf_character_negative_control.png"], f"Evidence negative_screenshot must list the negative control capture, got {sorted(negative)}")
    for name, digest in negative.items():
        path = os.path.join(artifacts_dir, name)
        check_file_hash(path, digest, f"Negative screenshot {name} SHA")
        verify_wolf_screenshot(path, mode="negative_control")
        print(f"  [PASS] {name}: error banner verified ({diagnostic})")

    print("ALL WOLF RPG EDITOR CHARACTER RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return 0


def _directional_map(fixture_dir, direction, frame):
    """SampleMap.mps with event 0 moved to the directional capture cell showing one fixed pose."""
    with open(os.path.join(fixture_dir, "Data", "MapData", "SampleMap.mps"), "rb") as f:
        header, body = decompress_mps(f.read())
    map_data = parse_mps_body(body, version=header[0])
    event = dict(map_data["events"][0])
    event["x"], event["y"] = DIRECTIONAL_EVENT_CELL
    page = dict(event["pages"][0], gdir=direction, gframe=frame, flags=0)
    event["pages"] = [page]
    return compress_mps(header, dump_mps_body(dict(map_data, events=[event]), version=header[0]))


def run_capture(cfg=None):
    """Runs the composite, directional and negative Game.exe sessions and writes evidence."""
    cfg = cfg or get_target_config()
    game_exe = wolf.find_game_exe()
    wine = wolf.find_wine()
    version = wolf.wine_version(wine)
    build_target("wolf", output_dir=cfg["target_dir"], clean=True)
    target_char = os.path.join(cfg["target_dir"], SLOT)
    os.makedirs(cfg["artifacts_dir"], exist_ok=True)
    print(f"Preparing Wine prefix ({version})...")
    wolf.prepare_wine_prefix(wine)

    def ready(mode, pattern=None):
        return lambda path: bool(verify_wolf_screenshot(path, target_char_path=target_char, mode=mode, expected_pat=pattern))

    print("Executing WOLF Game.exe positive composite control under Xvfb...")
    pos_path = os.path.join(cfg["artifacts_dir"], "wolf_character_positive.png")
    pos = wolf.run_session(cfg["fixture_dir"], game_exe, wine, pos_path, ready("positive"), charachip_png=target_char)
    pos_result = verify_wolf_screenshot(pos_path, target_char_path=target_char, mode="positive")

    directional = {}
    for name, (direction, frame, pattern, desc) in DIRECTIONAL_SHOTS.items():
        path = os.path.join(cfg["artifacts_dir"], name)
        wolf.run_session(cfg["fixture_dir"], game_exe, wine, path, ready("directional", pattern),
                         charachip_png=target_char, map_override=_directional_map(cfg["fixture_dir"], direction, frame))
        directional[name] = verify_wolf_screenshot(path, target_char_path=target_char, mode="directional", expected_pat=pattern)
        print(f"  Captured {name} ({desc})")

    print("Executing WOLF Game.exe negative control under Xvfb...")
    neg_path = os.path.join(cfg["artifacts_dir"], "wolf_character_negative_control.png")
    neg = wolf.run_session(cfg["fixture_dir"], game_exe, wine, neg_path, ready("negative_control"))
    if not neg.error_log:
        raise ValueError("Negative control did not write Game_ErrorLog.txt")
    diagnostic = _diagnostic_from_error_log(neg.error_log)
    if diagnostic != ERROR_LOG_ENTRY:
        raise ValueError(f"Negative control reported an unexpected missing file: {diagnostic}")

    error_log = os.path.join(cfg["artifacts_dir"], "Game_ErrorLog.txt")
    with open(error_log, "wb") as f:
        f.write(neg.error_log)
    logs = {}
    for kind, session in (("positive", pos), ("negative", neg)):
        logs[kind] = os.path.join(cfg["artifacts_dir"], f"{kind}_runtime.log")
        with open(logs[kind], "w", encoding="utf-8") as f:
            f.write(session.log)

    fixture_manifest = load_json(os.path.join(cfg["fixture_dir"], "fixture_manifest.json"))
    evidence = {key: cfg[key] for key in (
        "target", "engine", "runtime", "runtime_version", "release_tag", "release_commit", "runtime_archive_sha256",
        "game_exe_sha256", "category", "wolf_resource_class", "expected_character_slot", "runtime_reference",
        "direction_mode", "animation_patterns", "canonical_asset_id", "canonical_asset_sha256",
        "source_character_index", "transform_policy")}
    evidence.update({
        "target_manifest_sha256": sha256_file(os.path.join(cfg["target_dir"], "manifest.json")),
        "target_png_sha256": sha256_file(target_char),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "fixture_project_data_hashes": {k: v["sha256"] for k, v in fixture_manifest["project_data"].items()},
        "fixture_support_asset_hashes": {k: v["sha256"] for k, v in fixture_manifest["support_assets"].items()},
        "positive_lookup_result": pos_result["extracted_lookup"],
        "negative_diagnostic": diagnostic,
        "negative_error_log_sha256": sha256_file(error_log),
        "positive_runtime_log_sha256": sha256_file(logs["positive"]),
        "negative_runtime_log_sha256": sha256_file(logs["negative"]),
        "positive_screenshots": {os.path.basename(pos_path): sha256_file(pos_path),
                                 **{name: sha256_file(os.path.join(cfg["artifacts_dir"], name)) for name in DIRECTIONAL_SHOTS}},
        "negative_screenshot": {os.path.basename(neg_path): sha256_file(neg_path)},
        "directional_captures": {name: {"pattern": r["pattern"], "position": r["position"]} for name, r in directional.items()},
        "runtime_environment_metadata": {"os": sys.platform, "wine_version": version,
                                         "capture_method": "xvfb_ffmpeg_x11grab_640x480"},
        "timestamp": evidence_timestamp(),
    })
    write_evidence(cfg["evidence_path"], evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description="SuperRTP WOLF RPG Editor character runtime verifier (Game.exe under Wine)")
    parser.add_argument("--verify", action="store_true", help="Verify evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live Game.exe first")
    parser.add_argument("--artifacts-dir", default=None,
                        help="Write/verify artifacts here instead of artifacts/runtime/wolf/character (e.g. a CI temp dir)")
    parser.add_argument("--evidence-file", default=None, help="Evidence file to verify")
    args = parser.parse_args()
    cfg = get_target_config(os.path.abspath(args.artifacts_dir) if args.artifacts_dir else None)
    if args.run_capture:
        run_capture(cfg)
    verify_evidence_chain(args.evidence_file, cfg)


if __name__ == "__main__":
    main()
