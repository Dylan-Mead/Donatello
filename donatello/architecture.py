"""Finds, loads, and summarizes a repository's architecture document.

Donatello expects a single system architecture and component design document
per repository, by default ``ARCHITECTURE.md`` at the repository root (a
common convention alongside files like ``README.md`` and ``CONTRIBUTING.md``).
The template below is intentionally compact: it is sent verbatim to small,
local models as planning/coding context, so it favors a short, fixed set of
sections over exhaustive detail.
"""

from __future__ import annotations

from pathlib import Path

FILENAME = "ARCHITECTURE.md"

# Existing documents are recognized under these repository-relative paths,
# checked in order. A missing document is always created at FILENAME.
_CANDIDATES = (
    FILENAME,
    "architecture.md",
    "docs/ARCHITECTURE.md",
    "docs/architecture.md",
    ".github/ARCHITECTURE.md",
)

TEMPLATE = """# Architecture

<!-- Maintained by Donatello: a compact map of this system's components and
     data flow. Keep each section short; update only what a change affects. -->

## Overview
One to three sentences: what the system does and who or what uses it.

## Components
- `component_name` -- one-line responsibility.

## Data Flow
1. Step-by-step path a request or piece of data takes through the components
   listed above.

## Interfaces
- Public APIs, CLI commands, or files other components/consumers depend on.

## Dependencies
- External services, libraries, or data stores this system relies on.

## Decisions
- YYYY-MM-DD: notable architectural decision or trade-off and why.
"""


def find(root: Path) -> Path | None:
    """Return the path to the repository's architecture document, if any."""
    for candidate in _CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    return None


def load(root: Path) -> tuple[Path, str | None]:
    """Return (path, content). Content is None when no document exists yet.

    The returned path is the existing document's path, or the canonical
    ``FILENAME`` location when none exists yet.
    """
    path = find(root)
    if path is None:
        return root / FILENAME, None
    return path, path.read_text(encoding="utf-8")


def context_block(root: Path) -> str:
    """Build compact model-facing context describing the architecture document."""
    path, content = load(root)
    relative = path.relative_to(root).as_posix()
    if content is None:
        return (
            f"No system architecture and component design document exists yet "
            f"(expected at {relative}). If this task establishes or changes "
            f"architecture, components, interfaces, or data flow, create it using "
            f"this compact template, filled in for this project:\n{TEMPLATE}"
        )
    return (
        f"System architecture and component design document ({relative}). "
        f"Update only the sections this task affects, and keep it concise:\n{content}"
    )
