"""Read, check and write data/listings.json."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads(Path(__file__).with_name("listing.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(SCHEMA)


class CatalogError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        shown = "\n".join(f"  - {problem}" for problem in problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"{len(problems)} catalog problem(s):\n{shown}{more}")
        self.problems = problems


def load(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CatalogError([f"{path.name}: expected a JSON array"])
    return data


def problems(listings: list) -> list[str]:
    found = []
    seen: set[str] = set()
    for index, row in enumerate(listings):
        label = row.get("id", f"#{index}") if isinstance(row, dict) else f"#{index}"
        for error in _VALIDATOR.iter_errors(row):
            where = "/".join(str(part) for part in error.absolute_path) or "record"
            found.append(f"{label} {where}: {error.message}")
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            if row["id"] in seen:
                found.append(f"{label}: duplicate id")
            seen.add(row["id"])
    return found


def check(listings: list) -> None:
    found = problems(listings)
    if found:
        raise CatalogError(found)


def dumps(listings: list[dict]) -> str:
    ordered = sorted(
        listings,
        key=lambda row: (row["status"], row["company"].lower(), row["title"].lower(), row["id"]),
    )
    return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"


def write_all(files: dict[Path, str]) -> None:
    """Write every file to a temporary sibling first, then swap them all in."""
    staged: list[tuple[str, Path]] = []
    try:
        for path, text in files.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            staged.append((temporary, path))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            if os.path.exists(temporary):
                os.unlink(temporary)
