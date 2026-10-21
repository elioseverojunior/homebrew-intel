"""Estimate how expensive each unbottled Brewfile formula is to build on Intel."""

import logging
import math
import urllib.request

from brewfile_classify import NEEDS_BUILD, runtime_closure

LOG = logging.getLogger("brewfile-audit")

# Rough relative cost of compiling the formula itself (llvm ~ several hours).
SELF_COST = {
    "qtwebengine": 60,
    "qt": 45,
    "llvm": 40,
    "julia": 40,
    "swift": 40,
    "rust": 35,
    "ghc": 30,
    "dotnet": 30,
    "deno": 30,
    "texlive": 30,
    "gcc": 25,
    "pypy3.11": 25,
    "openjdk": 20,
    "qtbase": 20,
    "pandoc": 20,
    "emscripten": 20,
    "vtk": 20,
    "node": 15,
    "zig": 15,
    "bazel": 15,
    "mysql": 15,
    "opencv": 15,
    "boost": 12,
    "cabal-install": 10,
    "gdal": 10,
    "lld": 10,
    "erlang": 8,
    "grpc": 8,
    "ffmpeg": 8,
    "z3": 8,
    "python": 6,
    "php": 6,
    "ocaml": 6,
    "postgresql": 6,
    "protobuf": 5,
    "go": 4,
    "ruby": 4,
    "binutils": 4,
    "icu4c": 4,
    "imagemagick": 4,
    "cmake": 3,
    "openssl": 3,
    "glib": 3,
    "harfbuzz": 3,
    "perl": 3,
    "abseil": 3,
}
# Extra cost a build system / toolchain in the build closure adds to a consumer.
TOOLCHAIN_COST = {
    "rust": 3,
    "go": 1,
    "cmake": 2,
    "meson": 1.5,
    "ghc": 6,
    "cabal-install": 4,
    "openjdk": 2,
    "node": 1.5,
    "zig": 3,
    "swift": 3,
    "llvm": 4,
    "boost": 2,
    "qt": 5,
    "ninja": 0,
    "python": 0.5,
    "gcc": 3,
    "bazel": 5,
    "dotnet": 5,
    "erlang": 2,
    "ocaml": 2,
}


def base_name(name):
    """Strip a versioned suffix: llvm@20 -> llvm, python@3.14 -> python."""
    return name.split("@", 1)[0]


class BuildRequirements:
    """Memoized set of formulas needed to build a formula from source, recursively."""

    def __init__(self, records, api):
        self.records, self.api, self.memo = records, api, {}

    def of(self, name, stack=()):
        if name in self.memo or name in stack:
            return self.memo.get(name, set())
        record, required = self.records[name], set()
        for dep in runtime_closure(record["build_deps"] + record["runtime_deps"], self.api):
            required.add(dep)
            if dep in self.records and self.records[dep]["class"] in NEEDS_BUILD:
                required |= self.of(dep, (*stack, name))
        self.memo[name] = required
        return required


def annotate_fan_in(records, direct, api, requirements):
    fan_in = {n: set() for n in records}
    build_fan_in = {n: set() for n in records}
    for entry in direct:
        roots = [entry] if entry in api["formulas"] else records[entry]["runtime_deps"]
        closure = (runtime_closure(roots, api) | {entry}) & records.keys()
        for name in closure:
            fan_in[name].add(entry)
        for name in (n for n in closure if records[n]["class"] in NEEDS_BUILD):
            for needed in (requirements.of(name) | {name}) & records.keys():
                build_fan_in[needed].add(entry)
    for name, record in records.items():
        record["fan_in"], record["fan_in_entries"] = len(fan_in[name]), sorted(fan_in[name])[:40]
        record["build_fan_in"] = len(build_fan_in[name])


def build_weight(record, unbottled, toolchains):
    base = SELF_COST.get(base_name(record["name"]), 0)
    if not base:
        base = 1 + sum(TOOLCHAIN_COST.get(t, 0) for t in toolchains)
    size_mb = (record.get("source_bytes") or 0) / 1e6
    return round(base + min(size_mb / 10, 30) + 0.1 * len(unbottled), 2)


def build_priority(record):
    urgency = 1.0 if record["class"] == "NO_INTEL_BOTTLE" else 0.6
    reach = max(record["fan_in"], record["build_fan_in"])
    return round(record["build_weight"] * (1 + math.log2(1 + reach)) * urgency, 2)


def annotate_build_cost(records, requirements):
    for record in records.values():
        if record["class"] not in NEEDS_BUILD:
            continue
        required = requirements.of(record["name"]) & records.keys()
        unbottled = sorted(n for n in required if records[n]["class"] in NEEDS_BUILD)
        toolchains = sorted({base_name(n) for n in required if base_name(n) in TOOLCHAIN_COST})
        record["build_closure_unbottled"], record["build_toolchains"] = unbottled, toolchains
        record["build_weight"] = build_weight(record, unbottled, toolchains)
        record["priority"] = build_priority(record)


def head_content_length(url):
    if not url.startswith("https://"):
        return None
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "brewfile-audit"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - https only, checked above
            return int(response.headers.get("Content-Length") or 0) or None
    except (OSError, ValueError) as error:
        LOG.info("HEAD %s failed: %s", url, error)
        return None


def annotate_source_sizes(records, limit):
    """HEAD the heaviest candidates' source tarballs, then re-score them."""
    ranked = sorted((r for r in records.values() if "priority" in r), key=lambda r: -r["priority"])
    for record in ranked[:limit]:
        record["source_bytes"] = head_content_length(record["url"])
        LOG.info("%s source %s bytes", record["name"], record["source_bytes"])
        record["build_weight"] = build_weight(record, record["build_closure_unbottled"], record["build_toolchains"])
        record["priority"] = build_priority(record)
