"""LLM-based text cleanup: transform raw transcripts into polished text."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def prompts_dir(vault_dir: Path) -> Path:
    """Return the prompts directory, creating it if needed."""
    pdir = vault_dir.parent / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


def list_prompt_profiles(vault_dir: Path) -> list[dict]:
    """List all available prompt profiles."""
    pdir = prompts_dir(vault_dir)
    result = []
    for path in sorted(pdir.glob("*.txt")):
        first_line = path.read_text().split("\n", 1)[0].strip()
        result.append({
            "name": path.stem,
            "preview": first_line[:100],
        })
    return result


def load_prompt(vault_dir: Path, name: str) -> str:
    """Load a prompt profile by name."""
    path = prompts_dir(vault_dir) / f"{name}.txt"
    if not path.exists():
        return ""
    return path.read_text().strip()


def save_prompt(vault_dir: Path, name: str, content: str) -> Path:
    """Save a prompt profile."""
    pdir = prompts_dir(vault_dir)
    path = pdir / f"{name}.txt"
    path.write_text(content.strip() + "\n")
    logger.info("Prompt saved: %s", name)
    return path


def delete_prompt(vault_dir: Path, name: str) -> bool:
    """Delete a prompt profile."""
    path = prompts_dir(vault_dir) / f"{name}.txt"
    if path.exists():
        path.unlink()
        return True
    return False


def build_system_prompt(vault_dir: Path, profile_names: list[str]) -> str:
    """Build a combined system prompt from selected profiles."""
    parts = []
    for name in profile_names:
        text = load_prompt(vault_dir, name)
        if text:
            parts.append(text)

    if not parts:
        parts.append(DEFAULT_PROMPT)

    return "\n\n".join(parts)


def cleanup_text(
    raw_text: str,
    system_prompt: str,
    provider: str = "anthropic",
    model: str = "claude-haiku-4-5-20251001",
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Send raw transcript to LLM for cleanup. Returns cleaned text."""

    if provider == "anthropic":
        return _cleanup_anthropic(raw_text, system_prompt, model, api_key)
    elif provider == "openai":
        return _cleanup_openai(raw_text, system_prompt, model, api_key, base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _cleanup_anthropic(raw_text: str, system_prompt: str, model: str, api_key: str | None) -> str:
    from anthropic import Anthropic

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key

    client = Anthropic(**kwargs)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": raw_text}],
    )
    return response.content[0].text


def _cleanup_openai(
    raw_text: str, system_prompt: str, model: str,
    api_key: str | None, base_url: str | None,
) -> str:
    from openai import OpenAI

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
    )
    return response.choices[0].message.content


DEFAULT_PROMPT = """Du bist ein erfahrener Lektor. Deine Aufgabe ist es, ein Diktat-Rohtranskript
in sauberen, lesbaren Text umzuwandeln.

Regeln:
- Fuellwoerter entfernen (aehm, also, sozusagen, quasi, irgendwie)
- Satzstellung korrigieren, gesprochene Sprache in Schriftsprache umwandeln
- Wiederholungen und Versprecher bereinigen
- Absaetze sinnvoll strukturieren
- Inhalt und Aussage NICHT veraendern
- Fachbegriffe und Eigennamen BEIBEHALTEN
- Keine eigenen Ergaenzungen oder Interpretationen
- Ausgabe nur der bereinigte Text, keine Kommentare oder Erklaerungen"""
