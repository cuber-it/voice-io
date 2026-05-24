"""Glossary management: word lists that improve Whisper recognition."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def glossary_dir(vault_dir: Path) -> Path:
    """Return the glossary directory, creating it if needed."""
    gdir = vault_dir.parent / "glossaries"
    gdir.mkdir(parents=True, exist_ok=True)
    return gdir


def list_glossaries(vault_dir: Path) -> list[dict]:
    """List all available glossaries."""
    gdir = glossary_dir(vault_dir)
    result = []
    for path in sorted(gdir.glob("*.txt")):
        entries = parse_glossary(path)
        result.append({
            "name": path.stem,
            "entries": len(entries),
            "path": str(path),
        })
    return result


def parse_glossary(path: Path) -> list[dict]:
    """Parse a glossary file. Returns list of {word, description}."""
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            word, desc = line.split("|", 1)
            entries.append({"word": word.strip(), "description": desc.strip()})
        else:
            entries.append({"word": line, "description": ""})
    return entries


def load_glossary(vault_dir: Path, name: str) -> list[dict]:
    """Load a specific glossary by name."""
    path = glossary_dir(vault_dir) / f"{name}.txt"
    if not path.exists():
        return []
    return parse_glossary(path)


def save_glossary(vault_dir: Path, name: str, entries: list[dict]) -> Path:
    """Save a glossary. Returns the file path."""
    gdir = glossary_dir(vault_dir)
    path = gdir / f"{name}.txt"
    lines = []
    for entry in entries:
        word = entry.get("word", "").strip()
        desc = entry.get("description", "").strip()
        if not word:
            continue
        if desc:
            lines.append(f"{word} | {desc}")
        else:
            lines.append(word)
    path.write_text("\n".join(lines) + "\n")
    logger.info("Glossary saved: %s (%d entries)", name, len(lines))
    return path


def delete_glossary(vault_dir: Path, name: str) -> bool:
    """Delete a glossary file."""
    path = glossary_dir(vault_dir) / f"{name}.txt"
    if path.exists():
        path.unlink()
        return True
    return False


def build_initial_prompt(vault_dir: Path, glossary_names: list[str], language: str) -> str:
    """Build a Whisper initial_prompt from selected glossaries."""
    words = []
    for name in glossary_names:
        entries = load_glossary(vault_dir, name)
        for entry in entries:
            word = entry["word"]
            desc = entry["description"]
            if desc:
                words.append(f"{word} ({desc})")
            else:
                words.append(word)

    if not words:
        return ""

    # Whisper uses initial_prompt as context hint
    prompt_parts = [f"Transkription auf {language}."]
    prompt_parts.append("Fachbegriffe: " + ", ".join(words) + ".")
    return " ".join(prompt_parts)
