"""Create and apply unified-diff patches for tap formulae."""

import difflib
import subprocess
import tempfile
from pathlib import Path


class PatchError(RuntimeError):
    pass


def make_patch(original: str, edited: str, relpath: str) -> str:
    if not original.endswith("\n") or not edited.endswith("\n"):
        msg = "both texts must end with a newline"
        raise ValueError(msg)
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            edited.splitlines(keepends=True),
            fromfile=f"a/{relpath}",
            tofile=f"b/{relpath}",
        ),
    )


def apply_patch(text: str, patch: str, *, name: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        source = workdir / "in"
        patch_file = workdir / "change.patch"
        output = workdir / "out"
        source.write_text(text, encoding="utf-8")
        patch_file.write_text(patch, encoding="utf-8")
        result = subprocess.run(
            ["patch", "--batch", "--forward", "--silent", "-o", str(output), str(source), str(patch_file)],
            check=False,
            capture_output=True,
            text=True,
            cwd=workdir,
        )
        if result.returncode != 0:
            msg = f"patch for {name} no longer applies: {result.stdout}{result.stderr}".rstrip()
            raise PatchError(msg)
        return output.read_text(encoding="utf-8")
