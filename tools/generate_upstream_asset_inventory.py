#!/usr/bin/env python3
"""Generate filename-only inventories from official upstream packages.

This tool reads archive/installer metadata. It never extracts creative media and it
never copies upstream bytes into the repository. The generated inventories contain
only interoperability facts: relative paths, category names, and locale aliases.

The five RPG Maker packages must be downloaded separately from the official URLs in
``registry/upstream-assets/sources.json``. WOLF's full archive and EasyRPG's pinned
``rtp_table.cpp`` are separate inputs because they provide WOLF bundle paths and the
official Japanese/Traditional Chinese RM2k-family aliases respectively.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile


CREATIVE_EXTENSIONS = {".ico", ".jpg", ".mid", ".ogg", ".png", ".wav"}
ARCHIVES = {
    "rm2000": {
        "filename": "rpg2000_rtp_installer.exe",
        "url": "https://assets.rpgmakerweb.com/rpg2000_rtp_installer.exe",
        "sha256": "ec82b92da65ca6fdb2d3df25dfbcd7f2bb716e4fe63a079e8e5e396e91fa5e29",
        "parser": "nsis",
    },
    "rm2003": {
        "filename": "rpg2003_rtp_installer.zip",
        "url": "https://assets.rpgmakerweb.com/rpg2003_rtp_installer.zip",
        "sha256": "ddd519b50a22a2a95beeb831d29f7d7d92ae6263f953491163b446b808b66863",
        "parser": "nested-nsis",
        "member": "rpg2003_rtp_installer.exe",
    },
    "rmxp": {
        "filename": "xp_rtp104e.exe",
        "url": "https://assets.rpgmakerweb.com/xp_rtp104e.exe",
        "sha256": "b3bd20ad7f413b40ac233aafd2e061de1dc429c2eadb59d0b3157ba3c47f16b2",
        "parser": "inno",
    },
    "rmvx": {
        "filename": "vx_rtp102e.zip",
        "url": "https://assets.rpgmakerweb.com/vx_rtp102e.zip",
        "sha256": "8c82c02c876391d9585934454a629748d71b421c4957ada1dff8dc4b013ce403",
        "parser": "nested-inno",
        "member": "RPGVX_RTP/Setup.exe",
    },
    "rmvxace": {
        "filename": "RPGVXAce_RTP.zip",
        "url": "https://assets.rpgmakerweb.com/RPGVXAce_RTP.zip",
        "sha256": "7e93d0ead93a686218b7c671bf099ef42f09f536083bd0b2f0fa6423a39fc19b",
        "parser": "nested-inno",
        "member": "RTP100/Setup.exe",
        "companions": ["RTP100/Setup-1.bin"],
    },
}
EXPECTED_COUNTS = {
    "rm2000": 466,
    "rm2003": 676,
    "rmxp": 882,
    "rmvx": 439,
    "rmvxace": 748,
    "wolf": 645,
}
WOLF_SOURCE = {
    "url": "https://github.com/smokingwolf/tool_wolf_rpg_editor/releases/download/v3.717/WolfRPGEditor_3.717_full.zip",
    "version": "3.717",
    "sha256": "037e845bc0905c947e9ba337e0ad44771ce5122610188dac34cf08efe7dad608",
}
EASYRPG_SOURCE = {
    "url": "https://raw.githubusercontent.com/EasyRPG/Player/0.8.1.1/src/rtp_table.cpp",
    "version": "0.8.1.1",
    "sha256": "05e165d23add7287f8fa9582971547b1bffb35306421248393aeacd901e43cc0",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_source(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"Source hash mismatch for {path}: got {actual}, expected {expected}")


def is_creative_path(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in CREATIVE_EXTENSIONS


def list_nsis(executable: Path) -> list[str]:
    result = subprocess.run(
        ["7z", "l", "-slt", str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = set()
    for line in result.stdout.splitlines():
        if not line.startswith("Path = "):
            continue
        path = line.removeprefix("Path = ").replace("\\", "/")
        if not path.startswith("$PLUGINSDIR/") and is_creative_path(path):
            paths.add(path)
    return sorted(paths)


def list_inno(executable: Path, innoextract: Path, library_dir: Path | None) -> list[str]:
    env = os.environ.copy()
    if library_dir is not None:
        old = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = str(library_dir) if not old else f"{library_dir}:{old}"
    result = subprocess.run(
        [str(innoextract), "--list", str(executable)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    paths = set()
    for line in result.stdout.splitlines():
        match = re.match(r' - "app/(.*?)"(?: \[[^]]+\])? (?:\(|$)', line)
        if match and is_creative_path(match.group(1)):
            paths.add(match.group(1))
    return sorted(paths)


def list_rpg_maker(
    target: str,
    archives_dir: Path,
    innoextract: Path,
    library_dir: Path | None,
    temporary_dir: Path,
) -> list[str]:
    source = ARCHIVES[target]
    archive = archives_dir / source["filename"]
    check_source(archive, source["sha256"])
    parser = source["parser"]
    if parser == "nsis":
        return list_nsis(archive)
    if parser in {"nested-nsis", "nested-inno"}:
        extraction_dir = temporary_dir / target
        extraction_dir.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            members = [source["member"], *source.get("companions", [])]
            for member in members:
                bundle.extract(member, extraction_dir)
        executable = extraction_dir / source["member"]
        if parser == "nested-nsis":
            return list_nsis(executable)
        return list_inno(executable, innoextract, library_dir)
    if parser == "inno":
        return list_inno(archive, innoextract, library_dir)
    raise AssertionError(f"Unknown parser {parser}")


def list_wolf(archive: Path) -> list[str]:
    check_source(archive, WOLF_SOURCE["sha256"])
    prefix = "WOLF_RPG_Editor3/"
    paths = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if member.startswith(prefix + "Data/") and is_creative_path(member):
                paths.add(member.removeprefix(prefix))
    return sorted(paths)


def parse_cpp_rows(source: str, table: str, columns: int) -> list[list[str | None]]:
    marker = f"const char* const rtp_table_{table}[][{columns}] = {{"
    body = source.split(marker, 1)[1].split("\n};", 1)[0]
    rows = []
    for line in body.splitlines():
        match = re.search(r"\{(.*)\}", line)
        if not match:
            continue
        values = []
        for string_value, null_value in re.findall(r'"((?:[^"\\]|\\.)*)"|\b(nullptr)\b', match.group(1)):
            values.append(None if null_value else ast.literal_eval(f'"{string_value}"'))
        if values and values[0] is not None:
            rows.append(values)
    return rows


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


def lookup_english_paths(paths: list[str]) -> dict[tuple[str, str], str]:
    result = {}
    for path in paths:
        pure = PurePosixPath(path)
        if len(pure.parts) != 2:
            continue
        key = (pure.parent.name.lower(), pure.stem.casefold())
        if key in result:
            raise ValueError(f"Ambiguous case-insensitive RTP path: {path}")
        result[key] = path
    return result


def localized_path(category: str, stem: str, extension: str, category_case: dict[str, str]) -> str:
    return f"{category_case[category]}/{stem}{extension}"


def build_alias_rows(
    target: str,
    table_rows: list[list[str | None]],
    english_paths: list[str],
) -> tuple[list[str], list[list[str]]]:
    lookup = lookup_english_paths(english_paths)
    category_case = {
        path.split("/", 1)[0].lower(): path.split("/", 1)[0]
        for path in english_paths
        if "/" in path
    }
    headers = ["semantic_id", "category", "english_path", "japanese_path"]
    if target == "rm2003":
        headers.append("traditional_chinese_path")
    selected = []
    for row in table_rows:
        category = row[0]
        japanese = row[1]
        english = row[2]
        traditional_chinese = row[7] if target == "rm2003" else None
        if english is None and japanese is None and traditional_chinese is None:
            continue
        selected.append((category, english, japanese, traditional_chinese))

    aliases = []
    for index, (category, english, japanese, traditional_chinese) in enumerate(selected, 1):
        english_path = ""
        extension = ".png"
        if english is not None:
            english_path = lookup.get((category, english.casefold()), "")
            if not english_path:
                raise ValueError(f"No {target} installer path matches {category}/{english}")
            extension = PurePosixPath(english_path).suffix
        elif category == "music":
            extension = ".mid"
        elif category == "sound":
            extension = ".wav"
        row_out = [
            f"{target}-{index:04d}",
            category_case[category],
            english_path,
            localized_path(category, japanese, extension, category_case) if japanese else "",
        ]
        if target == "rm2003":
            row_out.append(
                localized_path(category, traditional_chinese, extension, category_case)
                if traditional_chinese
                else ""
            )
        aliases.append(row_out)
    return headers, aliases


def write_lines(path: Path, values: list[str]) -> None:
    path.write_text("".join(f"{value}\n" for value in values), encoding="utf-8", newline="\n")


def write_tsv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives-dir", type=Path, required=True)
    parser.add_argument("--wolf-archive", type=Path, required=True)
    parser.add_argument("--easyrpg-table", type=Path, required=True)
    parser.add_argument("--innoextract", type=Path, required=True)
    parser.add_argument("--innoextract-library-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    check_source(args.easyrpg_table, EASYRPG_SOURCE["sha256"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inventories: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="superrtp_inventory_") as temp:
        temp_path = Path(temp)
        for target in ARCHIVES:
            inventories[target] = list_rpg_maker(
                target,
                args.archives_dir,
                args.innoextract,
                args.innoextract_library_dir,
                temp_path,
            )
        inventories["wolf"] = list_wolf(args.wolf_archive)

    for target, paths in inventories.items():
        expected = EXPECTED_COUNTS[target]
        if len(paths) != expected:
            raise ValueError(f"{target}: got {len(paths)} paths, expected {expected}")
        write_lines(args.output_dir / f"{target}.txt", paths)

    cpp = args.easyrpg_table.read_text(encoding="utf-8")
    alias_files = {}
    for target, table, columns in (("rm2000", "2k", 5), ("rm2003", "2k3", 8)):
        headers, rows = build_alias_rows(target, parse_cpp_rows(cpp, table, columns), inventories[target])
        alias_path = args.output_dir / f"{target}-official-aliases.tsv"
        write_tsv(alias_path, headers, rows)
        alias_files[target] = {"file": alias_path.name, "rows": len(rows)}

    metadata = {
        "schema_version": 1,
        "snapshot_date": "2026-09-23",
        "scope": "Filename-only interoperability facts; no upstream creative content is included.",
        "rpg_maker_sources": {
            target: {
                "url": source["url"],
                "archive_sha256": source["sha256"],
                "inventory_file": f"{target}.txt",
                "asset_path_count": len(inventories[target]),
                "category_counts": category_counts(inventories[target]),
            }
            for target, source in ARCHIVES.items()
        },
        "wolf_source": {
            **WOLF_SOURCE,
            "inventory_file": "wolf.txt",
            "asset_path_count": len(inventories["wolf"]),
            "category_counts": category_counts(inventories["wolf"]),
        },
        "official_locale_alias_source": {
            **EASYRPG_SOURCE,
            "files": alias_files,
            "included_locales": {
                "rm2000": ["english", "japanese"],
                "rm2003": ["english", "japanese", "traditional_chinese"],
            },
            "excluded_columns": "Community translation/add-on columns are not publisher RTP inventories.",
        },
    }
    for target in inventories:
        path = args.output_dir / f"{target}.txt"
        if target in metadata["rpg_maker_sources"]:
            metadata["rpg_maker_sources"][target]["inventory_sha256"] = sha256_file(path)
        else:
            metadata["wolf_source"]["inventory_sha256"] = sha256_file(path)
    for target, item in alias_files.items():
        item["sha256"] = sha256_file(args.output_dir / item["file"])
    (args.output_dir / "sources.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
