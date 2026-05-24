"""Dictation macros: spoken trigger phrases get replaced with configured text."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def macros_dir(vault_dir: Path) -> Path:
    """Return the macros directory, creating it if needed."""
    mdir = vault_dir.parent / "macros"
    mdir.mkdir(parents=True, exist_ok=True)
    return mdir


def list_macro_sets(vault_dir: Path) -> list[dict]:
    """List all available macro sets."""
    mdir = macros_dir(vault_dir)
    result = []
    for path in sorted(mdir.glob("*.txt")):
        entries = parse_macros(path)
        result.append({
            "name": path.stem,
            "entries": len(entries),
        })
    return result


def parse_macros(path: Path) -> list[dict]:
    """Parse a macro file. Returns list of {trigger, replacement}."""
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        trigger, replacement = line.split("|", 1)
        trigger = trigger.strip()
        replacement = replacement.strip()
        # support escape sequences
        replacement = replacement.replace("\\n", "\n").replace("\\t", "\t")
        if trigger:
            entries.append({"trigger": trigger, "replacement": replacement})
    return entries


def load_macros(vault_dir: Path, name: str) -> list[dict]:
    """Load a specific macro set by name."""
    path = macros_dir(vault_dir) / f"{name}.txt"
    if not path.exists():
        return []
    return parse_macros(path)


def save_macros(vault_dir: Path, name: str, entries: list[dict]) -> Path:
    """Save a macro set."""
    mdir = macros_dir(vault_dir)
    path = mdir / f"{name}.txt"
    lines = []
    for entry in entries:
        trigger = entry.get("trigger", "").strip()
        replacement = entry.get("replacement", "").strip()
        if not trigger:
            continue
        # store escape sequences literally
        stored = replacement.replace("\n", "\\n").replace("\t", "\\t")
        lines.append(f"{trigger} | {stored}")
    path.write_text("\n".join(lines) + "\n")
    logger.info("Macros saved: %s (%d entries)", name, len(lines))
    return path


def delete_macros(vault_dir: Path, name: str) -> bool:
    """Delete a macro set file."""
    path = macros_dir(vault_dir) / f"{name}.txt"
    if path.exists():
        path.unlink()
        return True
    return False


def build_macro_table(vault_dir: Path, macro_names: list[str]) -> list[tuple[re.Pattern, str]]:
    """Build a compiled lookup table from selected macro sets.

    Returns list of (compiled_pattern, replacement) tuples,
    sorted longest trigger first to avoid partial matches.
    """
    all_macros = []
    for name in macro_names:
        all_macros.extend(load_macros(vault_dir, name))

    # sort by trigger length descending — longest match first
    all_macros.sort(key=lambda m: len(m["trigger"]), reverse=True)

    table = []
    for macro in all_macros:
        # case-insensitive, word boundary aware
        pattern = re.compile(
            r'\b' + re.escape(macro["trigger"]) + r'\b',
            re.IGNORECASE,
        )
        table.append((pattern, macro["replacement"]))

    return table


def expand_macros(text: str, macro_table: list[tuple[re.Pattern, str]]) -> str:
    """Apply all macros to a text string. Returns expanded text."""
    if not macro_table:
        return text

    for pattern, replacement in macro_table:
        text = pattern.sub(replacement, text)

    # clean up: multiple newlines, trailing spaces
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +\n', '\n', text)

    return text
