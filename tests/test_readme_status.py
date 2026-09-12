"""README's status section must name no release the CHANGELOG has moved past.

This is the failure class the homestead orchestrator hit with a stale PyPI
note it carried for hours: a status sentence nobody re-verified. Here the
README's "## Status" heading and prose named 0.2.0 while CHANGELOG.md's top
section had moved to 0.7.1 across five releases. The fix (see README.md) makes
the heading name no version and has the prose point at CHANGELOG.md instead of
typing one; this test is the scan that keeps it that way.

No existing test in this suite reads README.md for a version literal (the
closest, tests/test_render.py's PackagingTests, checks the distribution NAME
agrees across pyproject/`__init__`/release-please/release.yml — a different
claim), so this module is new rather than an extension.

Per house rule (a scan that has never fired has not been shown to check
anything): test_planted_stale_status_version_is_caught plants exactly the bug
this guard exists to catch, and test_current_status_version_passes is its
control.

The scan is deliberately narrow — headings (file-wide) and the "## Status"
section's body, not the whole README — because history paragraphs elsewhere
(e.g. "at 0.2.1 it was an unchecked one...") are allowed to name old versions;
only a *status claim* is not. Within the Status section itself, a paragraph
that opens with a recognized dated-history lead-in ("**At 0.2.0 ...**",
"**What 0.2.0 added ...**") is exempted the same way.
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")
CHANGELOG_TOP_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
HEADING_LINE_RE = re.compile(r"^#{1,6}\s.*$", re.MULTILINE)
STATUS_HEADING_RE = re.compile(r"^## Status\b.*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^## ", re.MULTILINE)
HISTORY_LEAD_RE = re.compile(r"^\*\*(?:At|What)\b")


def current_release(changelog_text):
    """The version the top ('## [x.y.z](...)') section of CHANGELOG.md names."""
    m = CHANGELOG_TOP_RE.search(changelog_text)
    if not m:
        raise AssertionError(
            "CHANGELOG.md has no '## [x.y.z]' top section to read the release from"
        )
    return m.group(1)


def stale_versions_in_headings(readme_text, current):
    """Every markdown heading in the text, checked for a version literal that
    is not the current release. Returns the offending heading lines."""
    bad = []
    for m in HEADING_LINE_RE.finditer(readme_text):
        line = m.group(0)
        if any(v != current for v in VERSION_RE.findall(line)):
            bad.append(line.strip())
    return bad


def _status_section_body(readme_text):
    m = STATUS_HEADING_RE.search(readme_text)
    if not m:
        return ""
    start = m.end()
    nxt = NEXT_HEADING_RE.search(readme_text, start)
    end = nxt.start() if nxt else len(readme_text)
    return readme_text[start:end]


def stale_versions_in_status_body(readme_text, current):
    """Paragraphs of the '## Status' section, checked for a version literal
    that is not the current release — skipping paragraphs that open with a
    recognized history lead-in. Returns the offending paragraphs (truncated)."""
    body = _status_section_body(readme_text)
    bad = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or HISTORY_LEAD_RE.match(para):
            continue
        if any(v != current for v in VERSION_RE.findall(para)):
            bad.append(para[:80])
    return bad


class ReadmeStatusVersionTests(unittest.TestCase):
    @staticmethod
    def _read(name):
        return (REPO_ROOT / name).read_text(encoding="utf-8")

    def test_readme_status_names_no_stale_version(self):
        current = current_release(self._read("CHANGELOG.md"))
        readme = self._read("README.md")

        bad_headings = stale_versions_in_headings(readme, current)
        self.assertEqual(
            bad_headings, [],
            f"README heading(s) name a version other than the CHANGELOG's "
            f"top release ({current}): {bad_headings}",
        )

        bad_status = stale_versions_in_status_body(readme, current)
        self.assertEqual(
            bad_status, [],
            f"README '## Status' section names a version other than the "
            f"CHANGELOG's top release ({current}): {bad_status}",
        )

    def test_planted_stale_status_version_is_caught(self):
        # The exact bug this guard exists to catch: a status heading (and
        # its prose) still naming an old release after the CHANGELOG moved on.
        current = "9.9.9"
        planted = (
            "## Status: spine (0.2.0, on PyPI)\n\n"
            "**0.2.0 is still a spine, and the version number still says "
            "so.** Some prose about what shipped.\n\n"
            "## Next section\n\n"
            "Unrelated prose.\n"
        )
        self.assertNotEqual(stale_versions_in_headings(planted, current), [])
        self.assertNotEqual(stale_versions_in_status_body(planted, current), [])

    def test_current_status_version_passes(self):
        # The control: the same shape, naming the current release (or no
        # release at all, and pointing at the CHANGELOG instead) is clean.
        current = "9.9.9"
        clean = (
            "## Status: spine\n\n"
            "**At 0.2.0 this was a spine, and the version number said so.** "
            "History paragraphs may still name 0.2.0.\n\n"
            "**What is true now:** the top section of `CHANGELOG.md` is the "
            f"release that is on PyPI — currently {current}.\n\n"
            "## Next section\n\n"
            "Unrelated prose.\n"
        )
        self.assertEqual(stale_versions_in_headings(clean, current), [])
        self.assertEqual(stale_versions_in_status_body(clean, current), [])


if __name__ == "__main__":
    unittest.main()
