"""
FLUX.2 concept jobs for every inventoried visual.

Each unique visual (a render key of tools/asset_generation/generate_full_inventory.py)
needs one or more FLUX "concept" images, which a structuring step later turns into the
exact engine layout (frame grids, tiles, alpha). This module only plans those jobs:
the prompt, concept size, background key colour and seed of each. It is standard
library only so the plan can be inspected without the generation environment.

Clean-room rules (AGENTS.md section 3, legal/CLEAN_ROOM_POLICY.md): prompts describe a
subject in plain words derived from the compatibility filename and never name an
engine, product, franchise or existing asset. The only image input ever supplied is the
front view this project generated for the same character, which conditions its side and
back views (FluxJob.reference) so the three views stay one design.

Families that are mostly structure (window skins, masks, the weapon sheet) are not
planned here; they stay procedural and are labelled as such in the manifest.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass

ART_DIRECTION_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                  "specs", "generation", "art-direction.v1.json")
# Bumping this re-plans every job; the worker regenerates any job whose prompt changed.
PROMPT_VERSION = 2

GREEN_KEY = (0, 255, 0)
MAGENTA_KEY = (255, 0, 255)
KEY_NAMES = {GREEN_KEY: "pure green #00FF00", MAGENTA_KEY: "pure magenta #FF00FF"}
# Subjects likely to be green themselves are keyed on magenta instead.
GREENISH = re.compile(r"green|grass|leaf|leaves|plant|vine|frog|slime|forest|tree|moss|herb|goblin|orc|lizard|snake|jelly|"
                      r"mandrag|treant|nepenth|chameleon|kappa|sylph|windspirit|oak|elf")

# Tokens in compatibility filenames that carry no descriptive meaning: numbering,
# creator tags and engine tileset codes.
NOISE_TOKENS = {"gd", "chara", "pochit", "pochi", "img", "ex", "ani", "base", "sp", "n", "new", "usm", "tapis",
                "garugaru", "makiba", "mel", "amania", "ipu", "auto", "ce", "cf", "ci", "cw", "sa", "sn", "st", "die"}

# Family -> art-direction subject group and prompt template.
GROUPS = {"creature": ("creature", "creature"), "battle-character": ("hero", "hero"),
          "charset-xp": ("character", "turnaround"), "charset-vx-single": ("character", "turnaround"),
          "portrait": ("character", "face"), "charset": ("sheet", "turnaround"), "charset-vx": ("sheet", "turnaround"),
          "faces": ("faces", "face"), "faces-vx": ("faces", "face"), "scene": ("scene", "scene"),
          "overlay": ("overlay", "overlay"), "fog": ("fog", "fog"), "transition": ("transition", "transition"),
          "effect": ("effect", "effect"), "icon": ("icon", "icon"), "tiles": ("tileset", "tileset"),
          "autotile": ("terrain", "terrain")}
KEYED_TEMPLATES = {"creature", "hero", "turnaround", "object-turnaround", "face", "icon"}
# A turnaround is drawn as three separate images: the front first, then the side (facing
# left) and back conditioned on it. The structurer mirrors the side view for facing right.
VIEWS = ("front", "side", "back")
VIEW_SIZE = {"turnaround": (512, 768), "object-turnaround": (768, 768)}
PART_COUNTS = {"charset": 8, "charset-vx": 8, "faces": 16, "faces-vx": 8}


def load_art_direction(path: str = ART_DIRECTION_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


ART = load_art_direction()


@dataclass(frozen=True)
class FluxJob:
    job_id: str          # "<creative_id>/<part>", unique
    creative_id: str
    family: str
    part: str
    prompt: str
    width: int
    height: int
    seed: int
    key_rgb: tuple = None  # background colour to key out, or None for opaque concepts
    brief: str = "authored"  # "authored": art direction has a description; "generic": filename words only
    reference: str = None  # job_id of the generated front view this view is conditioned on
    view: str = None       # "front", "side" or "back" for turnaround views
    view_kind: str = None  # "character" or "object" for turnaround views

    @property
    def prompt_sha256(self) -> str:
        text = f"{PROMPT_VERSION}\n{self.prompt}\n{self.width}x{self.height}\n{self.seed}"
        if self.reference:   # appended only when set, so jobs without a reference keep their hashes
            text += f"\nreference={self.reference}"
        return hashlib.sha256(text.encode()).hexdigest()

    def as_dict(self) -> dict:
        data = asdict(self)
        data["key_rgb"] = list(self.key_rgb) if self.key_rgb else None
        data["prompt_version"] = PROMPT_VERSION
        data["prompt_sha256"] = self.prompt_sha256
        return data


def _stem_tokens(creative_id: str) -> list:
    return creative_id.split(".", 2)[-1].split("-")


def subject_words(creative_id: str) -> str:
    """'visual.creature.gd-turnip-white' -> 'turnip white'; digits and filename noise dropped."""
    words = []
    for token in _stem_tokens(creative_id):
        token = re.sub(r"\d+$", "", token)
        if not token or token.isdigit() or token in NOISE_TOKENS or len(token) == 1:
            continue
        words.append(token)
    return " ".join(words) or "fantasy"


def variant_index(creative_id: str) -> int:
    """The number in a series name ('weapon05' -> 4, 'slime' -> 0), used to pick among description variants."""
    for token in _stem_tokens(creative_id):
        match = re.search(r"(\d+)$", token)
        if match:
            return max(0, int(match.group(1)) - 1)
    return 0


def _seed(job_id: str) -> int:
    return int.from_bytes(hashlib.sha256(job_id.encode()).digest()[:4], "big") & 0x7FFFFFFF


def _concept_size(width: int, height: int, longest: int = 1024) -> tuple:
    """Concept size with the target's aspect ratio, longest side `longest`, multiples of 64."""
    if width >= height:
        w, h = longest, max(256, round(longest * height / width / 64) * 64)
    else:
        w, h = max(256, round(longest * width / height / 64) * 64), longest
    return w, h


def _key_for(text: str) -> tuple:
    return MAGENTA_KEY if GREENISH.search(text) else GREEN_KEY


def describe(group: str, subject: str, index: int) -> tuple:
    """(description, brief) for a subject; list entries are chosen by `index`."""
    entry = ART["subjects"].get(group, {}).get(subject)
    if entry is None:
        return f"a {subject}", "generic"
    if isinstance(entry, list):
        return entry[index % len(entry)], "authored"
    return entry, "authored"


def render_prompt(template_name: str, description: str, key_rgb=None, **extra) -> str:
    style = ART["style"]
    background = ART["backgrounds"]["keyed"].format(key_name=KEY_NAMES[key_rgb]) if key_rgb else ""
    text = ART["families"][template_name].format(
        description=description, sprite=style["sprite"], scene=style["scene"], portrait=style["portrait"],
        texture=style["texture"], background=background, black=ART["backgrounds"]["black"], **extra)
    text = re.sub(r"\s+", " ", text).replace(" .", ".").strip()
    return re.sub(r"(^|[.:] )([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def jobs_for(creative_id: str, family: str, width: int, height: int) -> list:
    """The FLUX jobs one unique visual needs (empty for procedural-only families)."""
    if family not in GROUPS:
        return []
    group, template = GROUPS[family]
    subject = subject_words(creative_id)
    variant = variant_index(creative_id)
    if template == "turnaround" and subject in ART["object_subjects"]:
        template = "object-turnaround"
    jobs = []

    def add(part, description, brief, size, **extra):
        job_id = f"{creative_id}/{part}"
        key = _key_for(f"{subject} {description}") if template in KEYED_TEMPLATES else None
        prompt = render_prompt(template, description, key, **extra)
        jobs.append(FluxJob(job_id, creative_id, family, part, prompt, size[0], size[1], _seed(job_id), key, brief))

    def add_views(prefix, description, brief):
        """front, side and back as separate jobs; side and back are conditioned on the front."""
        key = _key_for(f"{subject} {description}")
        view_family = "view" if template == "turnaround" else "object"
        width, height = VIEW_SIZE[template]
        front_id = f"{creative_id}/{prefix}-front"
        for view in VIEWS:
            job_id = f"{creative_id}/{prefix}-{view}"
            prompt = render_prompt(f"{view_family}-{view}", description, key)
            jobs.append(FluxJob(job_id, creative_id, family, f"{prefix}-{view}", prompt, width, height, _seed(job_id), key,
                                brief, reference=None if view == "front" else front_id, view=view,
                                view_kind="character" if template == "turnaround" else "object"))

    expressions = ART["face_expressions"]
    if family in PART_COUNTS:
        prefix = "char" if template.endswith("turnaround") else "face"
        size = (1024, 512) if prefix == "char" else (512, 512)
        for index in range(PART_COUNTS[family]):
            description, brief = describe(group, subject, variant * PART_COUNTS[family] + index)
            if prefix == "char":
                add_views(f"char{index}", description, brief)
            else:
                add(f"face{index}", description, brief, size, expression=expressions[index % len(expressions)])
    elif family == "tiles":
        description, brief = describe(group, subject, variant)
        for material, phrase in ART["tile_materials"].items():
            add(material, description, brief, (512, 512), material=phrase[0].upper() + phrase[1:])
    elif template.endswith("turnaround"):
        description, brief = describe(group, subject, variant)
        add_views("char0", description, brief)
    else:
        description, brief = describe(group, subject, variant)
        size = {"creature": (768, 768), "hero": (768, 768),
                "face": (512, 512), "effect": (768, 768), "icon": (512, 512), "terrain": (512, 512),
                "transition": (768, 576)}.get(template) or _concept_size(width, height)
        extra = {"expression": expressions[0]} if template == "face" else {}
        add("main" if template != "face" else "face0", description, brief, size, **extra)
    return jobs


SAMPLE_CREATIVES_PER_FAMILY = 2

# Generation order: families that fill the most visible slots first.
FAMILY_PRIORITY = ("scene", "creature", "charset-xp", "charset-vx-single", "charset", "charset-vx", "battle-character",
                   "faces", "faces-vx", "portrait", "icon", "effect", "tiles", "autotile", "fog", "overlay", "transition")


def plan_jobs(plan_entries) -> list:
    """All jobs for a generate_full_inventory plan, deduplicated by render key, in priority order."""
    seen, jobs = set(), []
    for entry in plan_entries:
        if entry["media"] != "visual" or entry["alias_of"]:
            continue
        details = entry["details"]
        for job in jobs_for(entry["creative_id"], entry["family"], details["width"], details["height"]):
            if job.job_id not in seen:
                seen.add(job.job_id)
                jobs.append(job)
    rank = {family: i for i, family in enumerate(FAMILY_PRIORITY)}
    # Within a creative, a front view sorts before the side and back views that reference it.
    jobs.sort(key=lambda job: (rank.get(job.family, len(rank)), job.creative_id, job.part.rsplit("-", 1)[0],
                               VIEWS.index(job.view) if job.view else 0, job.part))
    # A small sample of every family first, so each structuring path is exercised early.
    sample_ids, per_family = set(), {}
    for job in jobs:
        taken = per_family.setdefault(job.family, set())
        if len(taken) < SAMPLE_CREATIVES_PER_FAMILY or job.creative_id in taken:
            taken.add(job.creative_id)
            sample_ids.add(job.job_id)
    return [j for j in jobs if j.job_id in sample_ids] + [j for j in jobs if j.job_id not in sample_ids]
