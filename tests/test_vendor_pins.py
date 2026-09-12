"""The vendored `tools/changelog_dedup.py` body is pinned to Forge's by hash.

`tools/changelog_dedup.py` is a copy whose canonical home is forge-play/Forge
`tools/changelog_dedup.py`; its own docstring says "fix the tool in forge-play
first, then re-sync", and CONTRIBUTING.md says not to let the copies diverge.
Nothing enforced that. This pin does, narrowly:

* **What is pinned:** the CODE BODY — everything from the line
  `from __future__ import annotations` to end of file, the same cut
  `tests/test_consent.py` already makes on the vendored consent core, so the
  two vendored files are held the same way. Measured 2026-09-12
  against Forge's copy: byte-identical, sha256
  `e3f31ef11105ae37c495c1745a94c6992ceb587c549cd016f24e83c778fd1320`,
  284 lines.
* **What is not:** the module docstring above that line. It is local on
  purpose — it carries this repo's own history (the first-release changelog
  gap, BUGS.md's entry on the 1.0.0 section) — and editing it must not trip
  the pin. Planted below.
* **What the pin catches, and what it does not.** It catches THIS copy
  moving without a decision: an edit made here, in place, that never went
  through Forge. It does *not* catch Forge moving — the constant is a
  measurement of Forge's body on one day, not a live read of it, so a fix
  landing upstream leaves this test green and this copy stale. Re-syncing
  stays a deliberate act; this only makes the other direction deliberate
  too. A named local override is allowed: record it here, beside the
  constant, and update the hash in the same commit.
"""

from __future__ import annotations

import ast
import hashlib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEDUP = REPO / "tools" / "changelog_dedup.py"

#: The body starts at this line. Everything before it is the local docstring.
BODY_START = "from __future__ import annotations"

#: sha256 of Forge's body (from `from __future__` to EOF), measured 2026-09-12.
FORGE_BODY_SHA256 = "e3f31ef11105ae37c495c1745a94c6992ceb587c549cd016f24e83c778fd1320"

#: Named local overrides, if any. None today: the body is Forge's verbatim.
#: Adding one means changing FORGE_BODY_SHA256 in the same commit and saying
#: here what diverged and why.
LOCAL_OVERRIDES: tuple[str, ...] = ()

RESYNC = (
    "re-sync from forge-play/Forge tools/changelog_dedup.py (body from "
    "`from __future__` to EOF), or record a named local override here"
)


def _body(text: str) -> str:
    """The pinned region: from the `from __future__` line to end of file."""
    return text[text.index(BODY_START) :]


def _body_sha256(text: str) -> str:
    return hashlib.sha256(_body(text).encode("utf-8")).hexdigest()


class VendoredChangelogDedupIsPinned(unittest.TestCase):
    def setUp(self):
        self.text = DEDUP.read_text(encoding="utf-8")

    def test_the_body_is_byte_identical_to_forge(self):
        self.assertEqual(_body_sha256(self.text), FORGE_BODY_SHA256, RESYNC)

    def test_only_the_docstring_precedes_the_body(self):
        """The local part is exactly the module docstring: the first
        statement after it is the `from __future__` line the pin starts at,
        so nothing local can hide between the two."""
        tree = ast.parse(self.text)
        self.assertTrue(ast.get_docstring(tree), "the local docstring is expected")
        first_code = tree.body[1]
        self.assertIsInstance(first_code, ast.ImportFrom)
        self.assertEqual(first_code.module, "__future__")
        self.assertEqual(self.text.count(BODY_START), 1)

    def test_planted_one_byte_change_in_the_body_is_caught(self):
        """Planted: the last byte of the file flipped — inside the body, so
        the pin must fail, and fail with the re-sync instruction."""
        last = self.text[-1]
        mutated = self.text[:-1] + ("x" if last != "x" else "y")
        self.assertEqual(len(mutated), len(self.text))
        self.assertNotEqual(_body_sha256(mutated), FORGE_BODY_SHA256)
        with self.assertRaisesRegex(AssertionError, "re-sync from forge-play/Forge"):
            self.assertEqual(_body_sha256(mutated), FORGE_BODY_SHA256, RESYNC)

    def test_planted_docstring_edit_does_not_trip_the_pin(self):
        """Planted the other way: a docstring edit — the part that is meant
        to stay local — leaves the body hash exactly where it was."""
        head, body = self.text.split(BODY_START, 1)
        self.assertIn('"""', head)
        edited = head.replace("WHY THIS EXISTS", "WHY THIS EXISTS (edited locally)", 1)
        self.assertNotEqual(edited, head, "the fixture edit must actually change the docstring")
        self.assertEqual(_body_sha256(edited + BODY_START + body), FORGE_BODY_SHA256)

    def test_no_local_override_is_recorded_while_the_body_is_verbatim(self):
        """An override list and a verbatim body cannot both be true."""
        self.assertEqual(LOCAL_OVERRIDES, ())


if __name__ == "__main__":
    unittest.main()
