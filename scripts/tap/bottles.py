"""Bottle release tags, root URLs and package versions for the Intel builder."""

import re
from collections import Counter
from collections.abc import Iterable, Mapping

ROOT_URL_BASE = "https://github.com/elioseverojunior/homebrew-intel/releases/download"

_ROOT_URL_LINE = re.compile(r'^\s*root_url\s+"([^"]+)"', re.MULTILINE)
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def pkg_version(formula: Mapping) -> str:
    version = formula["versions"]["stable"]
    revision = formula.get("revision", 0)
    return f"{version}_{revision}" if revision > 0 else version


def release_tag(name: str, version: str) -> str:
    return f"{name}-{version}"


def root_url(name: str, version: str) -> str:
    return f"{ROOT_URL_BASE}/{release_tag(name, version)}"


def bottle_release_tag(block: str) -> str | None:
    match = _ROOT_URL_LINE.search(block)
    return match.group(1).rstrip("/").rsplit("/", 1)[-1] if match else None


def api_core_commit(formulae: Iterable[Mapping]) -> str:
    heads = Counter(head for formula in formulae if _FULL_SHA.fullmatch(head := formula.get("tap_git_head") or ""))
    if not heads:
        message = "no 40-hex tap_git_head in the API snapshot"
        raise ValueError(message)
    return heads.most_common(1)[0][0]
