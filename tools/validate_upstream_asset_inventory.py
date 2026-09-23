#!/usr/bin/env python3
"""Validate SuperRTP's filename-only upstream creative-asset inventories."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import unicodedata

from repo import repo_path


INVENTORY_DIR = Path(repo_path("registry", "upstream-assets"))
CREATIVE_EXTENSIONS = {".ico", ".jpg", ".mid", ".ogg", ".png", ".wav"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def category_counts(paths: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        parts = path.split("/")
        if len(parts) == 1:
            category = "(root)"
        elif parts[0] in {"Audio", "Graphics", "Data"} and len(parts) >= 3:
            category = "/".join(parts[:2])
        else:
            category = parts[0]
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def validate_relative_asset_path(path: str, label: str) -> None:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or "\\" in path or ".." in pure.parts:
        raise ValueError(f"{label}: unsafe/non-portable path {path!r}")
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError(f"{label}: path is not Unicode NFC: {path!r}")
    if pure.suffix.lower() not in CREATIVE_EXTENSIONS:
        raise ValueError(f"{label}: non-creative extension in {path!r}")


def load_and_validate_inventory(target: str, record: dict) -> list[str]:
    path = INVENTORY_DIR / record["inventory_file"]
    if sha256_file(path) != record["inventory_sha256"]:
        raise ValueError(f"{target}: inventory SHA-256 does not match sources.json")
    paths = path.read_text(encoding="utf-8").splitlines()
    if paths != sorted(paths):
        raise ValueError(f"{target}: inventory is not sorted")
    if len(paths) != len(set(paths)):
        raise ValueError(f"{target}: inventory contains duplicate paths")
    if len(paths) != record["asset_path_count"]:
        raise ValueError(
            f"{target}: got {len(paths)} paths, sources.json declares {record['asset_path_count']}"
        )
    for asset_path in paths:
        validate_relative_asset_path(asset_path, target)
    actual_categories = category_counts(paths)
    if actual_categories != record["category_counts"]:
        raise ValueError(f"{target}: category counts do not match sources.json")
    return paths


def validate_aliases(target: str, record: dict, inventory: list[str]) -> None:
    path = INVENTORY_DIR / record["file"]
    if sha256_file(path) != record["sha256"]:
        raise ValueError(f"{target}: alias SHA-256 does not match sources.json")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != record["rows"]:
        raise ValueError(f"{target}: alias row count does not match sources.json")
    expected_headers = ["semantic_id", "category", "english_path", "japanese_path"]
    if target == "rm2003":
        expected_headers.append("traditional_chinese_path")
    if not rows or list(rows[0]) != expected_headers:
        raise ValueError(f"{target}: unexpected alias columns")

    for index, row in enumerate(rows, 1):
        expected_id = f"{target}-{index:04d}"
        if row["semantic_id"] != expected_id:
            raise ValueError(f"{target}: expected semantic ID {expected_id}, got {row['semantic_id']}")
        for locale_field in expected_headers[2:]:
            alias = row[locale_field]
            if alias:
                validate_relative_asset_path(alias, f"{target} {locale_field}")
                if alias.split("/", 1)[0] != row["category"]:
                    raise ValueError(f"{target}: alias category mismatch for {alias}")

    english = [row["english_path"] for row in rows if row["english_path"]]
    expected_english = [path for path in inventory if path != "icon.ico"]
    if sorted(english) != sorted(expected_english):
        raise ValueError(f"{target}: official English aliases do not cover every RTP media path")
    for locale_field in expected_headers[2:]:
        aliases = [row[locale_field] for row in rows if row[locale_field]]
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"{target}: duplicate {locale_field} aliases")


def validate() -> dict[str, int]:
    metadata_path = INVENTORY_DIR / "sources.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1:
        raise ValueError("Unsupported upstream inventory schema version")

    counts = {}
    inventories = {}
    for target, record in metadata["rpg_maker_sources"].items():
        inventories[target] = load_and_validate_inventory(target, record)
        counts[target] = len(inventories[target])
    wolf_record = metadata["wolf_source"]
    inventories["wolf"] = load_and_validate_inventory("wolf", wolf_record)
    counts["wolf"] = len(inventories["wolf"])

    alias_source = metadata["official_locale_alias_source"]
    for target, record in alias_source["files"].items():
        validate_aliases(target, record, inventories[target])
    return counts


def main() -> None:
    counts = validate()
    print("Upstream asset inventories are valid.")
    for target, count in counts.items():
        print(f"  {target}: {count} creative asset paths")
    print(f"  total: {sum(counts.values())} creative asset paths")


if __name__ == "__main__":
    main()
