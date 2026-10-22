"""Loader for enabled.toml, the list of core formulae this tap carries."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+_.@-]*$")
BASE_PATTERN = re.compile(r"^[0-9a-f]{40}$")
KINDS = ("generated", "patched")
ALLOWED_KEYS = frozenset({"kind", "base"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str
    base: str | None


def _validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        msg = f"{name}: invalid formula name"
        raise ConfigError(msg)


def _validate_keys(name: str, table: dict) -> None:
    unknown = sorted(set(table) - ALLOWED_KEYS)
    if unknown:
        msg = f"{name}: unknown key(s) {', '.join(unknown)}"
        raise ConfigError(msg)


def _validate_kind_and_base(name: str, kind: object, base: object) -> None:
    if kind not in KINDS:
        msg = f"{name}: kind must be one of {', '.join(KINDS)}, got {kind!r}"
        raise ConfigError(msg)
    if kind == "generated" and base is not None:
        msg = f"{name}: a generated formula must not set base"
        raise ConfigError(msg)
    if kind == "patched" and base is None:
        msg = f"{name}: a patched formula requires base"
        raise ConfigError(msg)
    if base is not None and not (isinstance(base, str) and BASE_PATTERN.match(base)):
        msg = f"{name}: base must be a 40-character lowercase hex commit SHA"
        raise ConfigError(msg)


def _build_entry(name: str, table: object) -> Entry:
    _validate_name(name)
    if not isinstance(table, dict):
        msg = f"{name}: formula entry must be a table"
        raise ConfigError(msg)
    _validate_keys(name, table)
    kind, base = table.get("kind"), table.get("base")
    _validate_kind_and_base(name, kind, base)
    return Entry(name, kind, base)


def parse_enabled(text: str) -> list[Entry]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        msg = f"invalid TOML: {error}"
        raise ConfigError(msg) from error
    formulae = document.get("formula", {})
    return sorted((_build_entry(name, table) for name, table in formulae.items()), key=lambda entry: entry.name)


def load_enabled(path: Path) -> list[Entry]:
    return parse_enabled(path.read_text(encoding="utf-8"))
