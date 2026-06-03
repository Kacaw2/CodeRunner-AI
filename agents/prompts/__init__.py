"""Versioned, externalized agent system prompts.

Prompts live as Markdown files alongside this module, each with a small
YAML-style frontmatter carrying ``name`` and ``version``. Keeping the version
next to the content means a single ``git diff`` shows both the text change and
the version bump — that is the change-audit trail (no separate registry table).

Existing imports such as ``from agents.tutor.prompt import TUTOR_SYSTEM_PROMPT``
keep working because the per-agent ``prompt.py`` modules now resolve their
constant through :func:`get_prompt`.
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent


def _parse_frontmatter(raw: str, name: str) -> tuple[dict[str, str], str]:
    """Split a ``---``-delimited frontmatter block from the prompt body."""
    if not raw.startswith("---"):
        raise ValueError(f"prompt '{name}' is missing required frontmatter")
    _, _, rest = raw.partition("---\n")
    front, sep, body = rest.partition("\n---\n")
    if not sep:
        raise ValueError(f"prompt '{name}' has an unterminated frontmatter block")
    meta: dict[str, str] = {}
    for line in front.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body.strip()


@lru_cache(maxsize=None)
def _load(name: str) -> tuple[str, str]:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no externalized prompt for agent '{name}' at {path}")
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"), name)
    version = meta.get("version", "0.0.0")
    if meta.get("name", name) != name:
        logger.warning(
            "prompt '%s' declares name='%s' in frontmatter (mismatch)", name, meta.get("name")
        )
    logger.debug("loaded prompt '%s' version %s", name, version)
    return body, version


def get_prompt(name: str) -> str:
    """Return the system prompt body for *name* (frontmatter stripped)."""
    return _load(name)[0]


def get_prompt_version(name: str) -> str:
    """Return the declared version string for *name*'s prompt."""
    return _load(name)[1]
