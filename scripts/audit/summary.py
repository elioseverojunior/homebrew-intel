"""Render reports/*.json into Markdown: one summary plus full per-class lists."""

import argparse
import collections
import json

from brew_api import REPORTS_DIR
from markdown import bullet, paragraph

FULL_LIST_CLASSES = {
    "NO_INTEL_BOTTLE": "formulae-no-intel-bottle",
    "OLD_INTEL_BOTTLE": "formulae-old-intel-bottle",
}


def read(name):
    return json.loads((REPORTS_DIR / f"{name}.json").read_text())


def by_installs(rows):
    return sorted(rows, key=lambda row: -row.get("installs_90d", 0))


def formula_section(formulae):
    counts = collections.Counter(row["class"] for row in formulae)
    lines = ["## Fórmulas (homebrew-core)", ""]
    lines += [bullet(f"`{cls}`: {count}") for cls, count in counts.most_common()]
    for cls in ["ARM_ONLY", "BLOCKED_BY_ARM_DEPENDENCY"]:
        names = ", ".join(f"`{row['name']}`" for row in formulae if row["class"] == cls)
        lines += ["", f"### {cls}", "", paragraph(names)]
    pinned = [row for row in formulae if row["intel_version"] != row["arm_version"]]
    lines += ["", "### Versão congelada no Intel", ""]
    pinned_lines = [bullet(f"`{row['name']}` {row['intel_version']} (ARM {row['arm_version']})") for row in pinned]
    lines += pinned_lines or [paragraph("")]
    for cls, page in FULL_LIST_CLASSES.items():
        top = ", ".join([f"`{row['name']}`" for row in by_installs(formulae) if row["class"] == cls][:40])
        lines += [
            "",
            f"### {cls} — 40 mais instaladas",
            "",
            paragraph(top),
            "",
            f"Lista completa: [{page}.md]({page}.md).",
        ]
    return lines


def cask_section(casks):
    lines = ["## Casks (homebrew-cask)", ""]
    for cls in ["UNAVAILABLE_ON_INTEL", "INTEL_DEPRECATED", "INTEL_VERSION_PINNED", "INTEL_OLD_MACOS_ONLY"]:
        rows = by_installs([row for row in casks if row["class"] == cls])
        lines += [f"### {cls} ({len(rows)})", ""]
        lines += [bullet(f"`{row['token']}`: {'; '.join(row['reasons'])}") for row in rows]
        lines.append("")
    return lines


def taps_section(taps, removed):
    lines = ["## Taps de terceiros", ""]
    lines += [bullet(f"`{row['item']}` ({row['tap']}): {'; '.join(row['reasons'])}") for row in taps]
    real = [row for row in removed if not row["moved"]]
    arm = ", ".join(f"`{row['name']}`" for row in real if row["arm_only"])
    lines += [
        "",
        "## Removidos do core/cask desde 2025-09",
        "",
        bullet(f"{len(real)} arquivos removidos; quase todos por EOL/abandono, não por Intel."),
        bullet(f"Eram arm64-only quando removidos: {arm}."),
        "",
    ]
    return lines


def full_list(formulae, cls):
    rows = by_installs([row for row in formulae if row["class"] == cls])
    lines = [f"# {cls} ({len(rows)})", "", "Ordenado por instalações nos últimos 90 dias.", ""]
    return lines + [bullet(f"`{row['name']}` {row['intel_version']}: {row['installs_90d']}") for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print written paths")
    args = parser.parse_args()
    formulae = read("formulae")
    summary = ["# Auditoria de suporte macOS Intel", ""]
    summary += [*formula_section(formulae), "", *cask_section(read("casks"))]
    summary += taps_section(read("taps"), read("removed"))
    outputs = {"intel-audit": summary}
    outputs |= {page: full_list(formulae, cls) for cls, page in FULL_LIST_CLASSES.items()}
    for page, lines in outputs.items():
        path = REPORTS_DIR / f"{page}.md"
        path.write_text("\n".join(lines).rstrip() + "\n")
        if args.verbose:
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
