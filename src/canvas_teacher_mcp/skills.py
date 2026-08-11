"""Skill tools — one tool per skill document, discovered at startup.

A skill is a methodology document. Its tool returns the document body and executes nothing;
the model then calls the execution tools the document names. Skills are tools rather than
resources because only a tool's description reaches the model automatically.

See `docs/ARCHITECTURE.md`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

from .canvas_root import root

# Shipped copy. Inside the package directory, so one path works from a source checkout and from
# an installed wheel alike.
_PACKAGE_SKILLS = Path(__file__).resolve().parent / "_data" / "skills"

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def _skills_dir() -> Path | None:
    """The tree's skills directory, or the packaged seed while the tree has none."""
    try:
        tree = root() / ".claude" / "skills"
    except Exception:  # noqa: BLE001 — no root yet is a normal pre-setup state
        tree = None
    if tree is not None and tree.is_dir() and any(tree.iterdir()):
        return tree
    return _PACKAGE_SKILLS if _PACKAGE_SKILLS.is_dir() else None


def _documents(base: Path) -> Iterator[Path]:
    """Every skill document. Both shapes count: `<name>/SKILL.md` and a bare `<name>.md`."""
    for child in sorted(base.iterdir()):
        if child.is_dir():
            doc = child / "SKILL.md"
            if doc.is_file():
                yield doc
        elif child.suffix == ".md":
            yield child


def _clean(value: str) -> str:
    """Drop a folded/literal block marker and any surrounding quotes."""
    if value[:1] in (">", "|"):
        value = value[1:].lstrip("-+ ")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def _frontmatter(text: str) -> dict[str, str]:
    """The leading `---` block as flat key -> value. Continuation lines fold into the key above."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    key = ""
    for line in match.group(1).splitlines():
        if key and line[:1].isspace():
            fields[key] = f"{fields[key]} {line.strip()}".strip()
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        fields[key] = value.strip()
    return {key: _clean(value) for key, value in fields.items()}


def _body(text: str) -> str:
    """The document without its frontmatter."""
    match = _FRONTMATTER.match(text)
    return text[match.end():] if match else text


def _declared_tools(value: str) -> list[str]:
    """`tools: [a, b]` or `tools: a, b` -> the names."""
    return [name.strip() for name in value.strip("[] ").split(",") if name.strip()]


def _reader(doc: Path) -> Callable[[], str]:
    """A tool that returns the document, read fresh so an edit takes effect without a restart."""

    def read_skill() -> str:
        return _body(doc.read_text(encoding="utf-8"))

    return read_skill


def register(server, execution_tools: set[str]) -> None:
    """Register one tool per skill, and refuse to start on a skill that names a tool we lack.

    `execution_tools` is what the `servers/` modules registered. A skill declaring
    `tools: [...]` is checked against it, so a skill still pointing at code that no longer
    exists is caught here instead of during a class.
    """
    base = _skills_dir()
    if base is None:
        return

    missing: list[str] = []
    collisions: list[str] = []
    seen: set[str] = set()
    for doc in _documents(base):
        text = doc.read_text(encoding="utf-8")
        fields = _frontmatter(text)
        fallback = doc.parent.name if doc.name == "SKILL.md" else doc.stem
        name = fields.get("name") or fallback
        description = fields.get("description") or f"The {name} skill document."

        # A `<name>/SKILL.md` and a stray `<name>.md` can claim the same name; the folder wins
        # because `_documents` yields it first.
        if name in seen:
            continue
        # A skill and an execution tool sharing a name would silently drop one of them — and the
        # dropped one is invisible, not broken, so nothing would ever report it. Stop instead.
        if name in execution_tools:
            collisions.append(name)
            continue
        seen.add(name)

        for declared in _declared_tools(fields.get("tools", "")):
            if declared not in execution_tools:
                missing.append(f"{name} -> {declared}")

        server.add_tool(_reader(doc), name=name, description=description)

    if collisions:
        raise RuntimeError(
            "a skill and an execution tool share a name, so one of them would be invisible: "
            + ", ".join(collisions) + ". Rename the tool."
        )
    if missing:
        raise RuntimeError(
            "skill declares a tool this server does not provide: " + "; ".join(missing)
        )
