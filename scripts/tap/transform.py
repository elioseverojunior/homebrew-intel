"""Pure, line-based transforms from a homebrew-core formula to this tap's."""

import re
from collections.abc import Set as AbstractSet

TAP = "homebrew-intel/tap"
BOTTLE_MARKER = "  # bottle block: written by brew pr-pull"

_BOTTLE_START = "  bottle do"
_BOTTLE_END = "  end"
_HEADER_PATTERN = re.compile(
    r"# Generated from Homebrew/homebrew-core@([0-9a-f]{40}) by scripts/tap/render\.py; do not edit\."
)


class TransformError(ValueError):
    pass


def header(commit: str, name: str) -> str:
    return (
        f"# Generated from Homebrew/homebrew-core@{commit} by scripts/tap/render.py; do not edit.\n"
        f"# Hand-written changes belong in patches/{name}.patch.\n"
    )


def parse_header(text: str) -> str:
    match = _HEADER_PATTERN.fullmatch(text.split("\n", 1)[0])
    if match is None:
        msg = "first line is not a generated-formula header"
        raise TransformError(msg)
    return match.group(1)


def _bottle_spans(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start, end) index pairs, end exclusive, of top-level bottle blocks."""
    spans = []
    index = 0
    while index < len(lines):
        if lines[index].rstrip() != _BOTTLE_START:
            index += 1
            continue
        end = next((i for i in range(index + 1, len(lines)) if lines[i].rstrip() == _BOTTLE_END), None)
        if end is None:
            msg = "bottle block has no closing end"
            raise TransformError(msg)
        spans.append((index, end + 1))
        index = end + 1
    return spans


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def mark_bottle_block(text: str, *, required: bool = True) -> str:
    lines = _lines(text)
    spans = _bottle_spans(lines)
    if len(spans) > 1:
        msg = f"expected one bottle block, found {len(spans)}"
        raise TransformError(msg)
    if not spans:
        if required:
            msg = "no bottle block found"
            raise TransformError(msg)
        return text
    start, end = spans[0]
    return "".join([*lines[:start], BOTTLE_MARKER + "\n", *lines[end:]])


def qualify_dependencies(text: str, tap_names: AbstractSet[str]) -> str:
    if not tap_names:
        return text
    names = "|".join(re.escape(name) for name in sorted(tap_names))
    pattern = re.compile(rf'^([ \t]*depends_on )"({names})"', re.MULTILINE)
    return pattern.sub(rf'\1"{TAP}/\2"', text)


def render_body(source: str, *, name: str, commit: str, tap_names: AbstractSet[str]) -> str:
    return header(commit, name) + qualify_dependencies(mark_bottle_block(source), tap_names)


def apply_bottle(body: str, bottle_block: str | None) -> str:
    if bottle_block is None:
        return body
    lines = _lines(body)
    marker = next((i for i, line in enumerate(lines) if line.rstrip() == BOTTLE_MARKER), None)
    if marker is None:
        msg = "bottle marker not found"
        raise TransformError(msg)
    return "".join([*lines[: marker + 1], bottle_block, *lines[marker + 1 :]])


def bottle_blocks(text: str) -> list[str]:
    lines = _lines(text)
    return ["".join(lines[start:end]) for start, end in _bottle_spans(lines)]


def extract_bottle_block(text: str) -> str | None:
    blocks = bottle_blocks(text)
    return blocks[0] if blocks else None


def _is_blank(line: str) -> bool:
    return not line.strip()


def _drop_span(lines: list[str], start: int, end: int) -> list[str]:
    rest = lines[end:]
    if start > 0 and rest and _is_blank(lines[start - 1]) and _is_blank(rest[0]):
        rest = rest[1:]
    return [*lines[:start], *rest]


def strip_bottle_block(text: str) -> str:
    lines = _lines(text)
    for start, end in reversed(_bottle_spans(lines)):
        lines = _drop_span(lines, start, end)
    return "".join(lines)
