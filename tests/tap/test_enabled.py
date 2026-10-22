import unittest

from enabled import ConfigError, Entry, parse_enabled

SHA = "0123456789abcdef0123456789abcdef01234567"


class ParseEnabledTest(unittest.TestCase):
    def test_parses_generated_and_patched(self):
        text = f'[formula.lz4]\nkind = "generated"\n\n[formula."go@1.21"]\nkind = "patched"\nbase = "{SHA}"\n'
        self.assertEqual(
            parse_enabled(text),
            [Entry("go@1.21", "patched", SHA), Entry("lz4", "generated", None)],
        )

    def test_empty_file_is_empty_list(self):
        self.assertEqual(parse_enabled(""), [])

    def assert_rejected(self, name, body):
        text = f'[formula."{name}"]\n{body}\n'
        with self.assertRaises(ConfigError) as caught:
            parse_enabled(text)
        self.assertIn(name, str(caught.exception))

    def test_rejects_unknown_kind(self):
        self.assert_rejected("lz4", 'kind = "weird"')

    def test_patched_requires_base(self):
        self.assert_rejected("lz4", 'kind = "patched"')

    def test_generated_forbids_base(self):
        self.assert_rejected("lz4", f'kind = "generated"\nbase = "{SHA}"')

    def test_base_must_be_40_hex(self):
        self.assert_rejected("lz4", 'kind = "patched"\nbase = "ABC"')
        self.assert_rejected("lz4", f'kind = "patched"\nbase = "{SHA.upper()}"')

    def test_rejects_unknown_key(self):
        self.assert_rejected("lz4", 'kind = "generated"\nfoo = 1')

    def test_rejects_bad_name(self):
        self.assert_rejected("Bad Name", 'kind = "generated"')

    def test_accepts_plus_and_at_names(self):
        text = '[formula."gtk+3"]\nkind = "generated"\n[formula."python@3.15"]\nkind = "generated"\n'
        self.assertEqual([entry.name for entry in parse_enabled(text)], ["gtk+3", "python@3.15"])
