"""Print the body of a failed-build issue from the untrusted artifact's log.

Usage: issue_body.py LOGS_DIR LOG_NAME NAME VERSION. The log comes from the
build host, so it is read only when LOG_NAME is a plain log file name and the
file is a regular file (not a symlink) directly in LOGS_DIR, itself a real
directory; only its last MAX_LOG_BYTES and 200 lines are used. Every `@`
becomes a fullwidth at sign (U+FF20) so the body mentions no one, and the log
sits in a backtick fence longer than any backtick run in it, so it cannot
close the fence and inject Markdown.
"""

import re
import sys
from pathlib import Path

from manifest_check import PATTERNS

MAX_LOG_BYTES = 60_000
MAX_LINES = 200
NEUTRAL_AT = "\uff20"  # FULLWIDTH COMMERCIAL AT: reads as @, mentions no one
_BACKTICKS = re.compile(r"`+")


def _log_path(logs_dir: Path, log_name: str) -> Path | None:
    if not PATTERNS["log"].fullmatch(log_name) or logs_dir.is_symlink() or not logs_dir.is_dir():
        return None
    path = logs_dir / log_name
    return path if path.is_file() and not path.is_symlink() else None


def log_tail(logs_dir: Path, log_name: str) -> str:
    """The last lines of the log, or `(no log)` when it may not be read."""
    if (path := _log_path(logs_dir, log_name)) is None:
        return "(no log)\n"
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - MAX_LOG_BYTES))
        text = handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)[-MAX_LINES:]
    return "".join(lines).rstrip("\n") + "\n" if lines else "(empty log)\n"


def issue_body(logs_dir: Path, log_name: str, name: str, version: str) -> str:
    tail = log_tail(logs_dir, log_name)
    fence = "`" * max([3, *(len(run) + 1 for run in _BACKTICKS.findall(tail))])
    body = f"Last {MAX_LINES} lines of the {name} {version} build log:\n\n{fence}\n{tail}{fence}\n"
    return body.replace("@", NEUTRAL_AT)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 4:  # noqa: PLR2004 - the four positional arguments of the usage line
        print("usage: issue_body.py LOGS_DIR LOG_NAME NAME VERSION", file=sys.stderr)
        return 2
    logs_dir, log_name, name, version = arguments
    print(issue_body(Path(logs_dir), log_name, name, version), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
