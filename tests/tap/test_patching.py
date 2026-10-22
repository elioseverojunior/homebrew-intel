import unittest

from patching import PatchError, apply_patch, make_patch

PATH = "Formula/p/podman.rb"


def _formula(*, arch_line: bool = True, filler: str = "x") -> str:
    lines = ["class Podman < Formula\n", '  desc "Tool"\n']
    if arch_line:
        lines.append("  depends_on arch: :arm64\n")
    lines.append('  depends_on "go" => :build\n')
    lines.extend(f"  # {filler} {index}\n" for index in range(30))
    lines.append("  def install\n    system 'make'\n  end\nend\n")
    return "".join(lines)


class PatchingTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        original = _formula()
        edited = _formula(arch_line=False)
        patch = make_patch(original, edited, PATH)
        self.assertIn(f"--- a/{PATH}", patch)
        self.assertIn(f"+++ b/{PATH}", patch)
        self.assertEqual(apply_patch(original, patch, name="x"), edited)

    def test_equal_inputs_give_empty_patch(self) -> None:
        self.assertEqual(make_patch(_formula(), _formula(), PATH), "")

    def test_patch_survives_unrelated_change(self) -> None:
        original = _formula()
        patch = make_patch(original, _formula(arch_line=False), PATH)
        drifted = original.replace("# x 29\n", "# changed 29\n")
        self.assertEqual(
            apply_patch(drifted, patch, name="x"),
            _formula(arch_line=False).replace("# x 29\n", "# changed 29\n"),
        )

    def test_conflict_raises_with_name(self) -> None:
        original = _formula()
        patch = make_patch(original, _formula(arch_line=False), PATH)
        conflicting = original.replace("depends_on arch: :arm64", "depends_on arch: :x86_64")
        with self.assertRaises(PatchError) as context:
            apply_patch(conflicting, patch, name="podman")
        self.assertIn("podman", str(context.exception))

    def test_requires_trailing_newline(self) -> None:
        with self.assertRaises(ValueError):
            make_patch("a", "b\n", PATH)
        with self.assertRaises(ValueError):
            make_patch("a\n", "b", PATH)


if __name__ == "__main__":
    unittest.main()
