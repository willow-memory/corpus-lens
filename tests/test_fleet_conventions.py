"""This repo's own tree, held to the fleet's published convention set.

Fleet plan decision 4: every repo carries this file, and the rules it checks
have ONE home — `reconciler.conventions`, which `reconciler conventions
--json` publishes. Nothing here restates a rule: the required files, the
hidden-type set and the required config comments are all *read* from the
published document, so a fleet-wide change to a rule reaches this test by
changing the one place it lives.

**This repo is stdlib-only, tests included**, so willow-reconciler is not a
dependency here. The published document is vendored verbatim instead, as
`tests/fleet_conventions.json` — saved from `reconciler conventions --json`
at willow-reconciler 0.6.0, pretty-printed the way that command prints it
(`json.dumps(..., indent=2)` plus a newline) — and pinned by hash below, so
this copy cannot drift from what was published without a recorded decision.
When `reconciler` happens to be importable, the vendored copy is also
checked equal to `reconciler.conventions.conventions()`; otherwise that one
check is skipped and the hash pin is the whole guarantee. The pin does not
catch the reconciler publishing a newer document — only this copy moving.

Adapted from the reconciler's own consumer test, with two facts of this
repo read rather than assumed:

* The test command CONTRIBUTING.md names is
  `python -m unittest discover -s tests` (with `-v` in its own listing);
  the PR template's checklist quotes exactly that string, which is what the
  rule is for.
* This repo keeps a **numbered** pile at `docs/ideas.md` (the index; the
  long-form reasoning stays in `IDEAS.md`), so `required_when_pile_exists`
  binds: `.github/workflows/trailers.yml` must run `reconciler verify`. Until
  E3-piles this repo had only the prose pile and the rule was vacuous; the
  test that asserted that vacuity is replaced by the real check, and
  `_pile_is_numbered` now guards the other direction — that the pile the
  rule binds on really is numbered, so the check cannot pass on a renamed
  prose file.

Every scan is planted in this same file: a helper that reads a tree and
reports on it is shown to report on a tree built to violate it (the house
rule: a scan that has never fired has not been shown to check anything).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The vendored copy of `reconciler conventions --json`, and the hash of
#: that file as published by willow-reconciler 0.6.0 (matched exactly on
#: 2026-09-12: `json.dumps(doc, indent=2)` + "\n", ASCII-escaped).
CONVENTIONS_JSON = REPO_ROOT / "tests" / "fleet_conventions.json"
CONVENTIONS_SOURCE = "willow-reconciler 0.6.0, `reconciler conventions --json`"
CONVENTIONS_SHA256 = "8c2ba122a7100141200d8c76ad086339f984446ab7e90dd9c27a092dbf7f5335"
RESYNC = (
    "re-sync from `reconciler conventions --json` (willow-reconciler >=0.6.0), "
    "or record the decision"
)

RULES = json.loads(CONVENTIONS_JSON.read_text(encoding="utf-8"))

RELEASE_PLEASE = ".github/workflows/release-please.yml"
RELEASE_CONFIG = "release-please-config.json"
CONTRIBUTING = "CONTRIBUTING.md"

#: This repo's numbered idea pile — the join target for `Idea-Id` trailers.
#: `IDEAS.md` beside it is the long-form reasoning and is not numbered.
PILE = "docs/ideas.md"

#: The `gh` invocation that arms auto-merge on the release PR — matched as
#: text; the arming is one line and this is its spelling.
ARMS_AUTOMERGE = "gh pr merge --auto"

#: The one test command this repo's CONTRIBUTING must name — the exact
#: string the PR template's checklist quotes.
TEST_COMMAND = "python -m unittest discover -s tests"

#: What makes a pile numbered, in the reconciler's own terms: a top-level
#: item — a line at column 0 opening with `<digits>.` and whitespace, which
#: is exactly `reconciler/parse.py`'s `_ITEM_RE` — or an id of the fleet's
#: shape written out (`willow-ideas-005`). Narrow on purpose: IDEAS.md names
#: versions like 0.2.0 in prose, and a nested `   1.` is not a top-level
#: item to the parser either, so neither may count.
_PILE_ID = re.compile(r"^\d+\.\s+\S|\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-ideas-\d{3}\b", re.MULTILINE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _arms_automerge(root: Path) -> bool:
    workflow = root / RELEASE_PLEASE
    return workflow.exists() and ARMS_AUTOMERGE in workflow.read_text(encoding="utf-8")


def _missing_when_armed(root: Path, required: list[str]) -> list[str]:
    if not _arms_automerge(root):
        return []
    return [f for f in required if not (root / f).exists()]


def _config_hidden_types(config_text: str) -> set[str]:
    sections = json.loads(config_text)["packages"]["."]["changelog-sections"]
    return {s["type"] for s in sections if s.get("hidden")}


def _config_missing_comments(config_text: str, required: list[str]) -> list[str]:
    package = json.loads(config_text)["packages"]["."]
    return [c for c in required if c not in package]


def _pile_is_numbered(pile_text: str) -> bool:
    """Whether a pile carries ids of the fleet's shape — the thing the
    `Idea-Id` trailer joins to, and the thing `reconciler verify` resolves."""
    return _PILE_ID.search(pile_text) is not None


def _missing_when_pile_exists(root: Path, required: list[str], pile: str | None) -> list[str]:
    """The files a repo with a numbered pile must carry. `pile` is the path
    of the numbered pile, or None for a repo that keeps no numbered pile —
    for which the rule is vacuous."""
    if pile is None or not (root / pile).exists():
        return []
    return [f for f in required if not (root / f).exists()]


def _names_test_command(contributing_text: str) -> bool:
    return TEST_COMMAND in contributing_text


# ── the vendored document ───────────────────────────────────────────────────


class TheVendoredDocumentIsThePublishedOne(unittest.TestCase):
    def test_the_vendored_copy_hashes_to_the_published_document(self):
        self.assertEqual(_sha256(CONVENTIONS_JSON), CONVENTIONS_SHA256, RESYNC)

    def test_the_document_is_the_schema_this_file_reads(self):
        self.assertEqual(RULES["schema"], "willow-fleet-conventions/1")
        for key in (
            "hidden_types",
            "release_cutting_types",
            "required_when_release_please_arms_automerge",
            "required_config_comments",
            "required_when_pile_exists",
            "contributing_must_name_test_command",
            "idea_id_trailer",
        ):
            self.assertIn(key, RULES)
            self.assertIn(key, RULES["sources"], "every rule names where it came from")

    def test_planted_one_byte_change_to_the_copy_is_caught(self):
        """Planted: the vendored file with its last byte flipped fails the
        pin, and fails with the re-sync instruction."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "fleet_conventions.json"
            data = CONVENTIONS_JSON.read_bytes()
            copy.write_bytes(data[:-1] + (b"x" if data[-1:] != b"x" else b"y"))
            self.assertEqual(len(copy.read_bytes()), len(data))
            self.assertNotEqual(_sha256(copy), CONVENTIONS_SHA256)
            with self.assertRaisesRegex(
                AssertionError, "re-sync from `reconciler conventions --json`"
            ):
                self.assertEqual(_sha256(copy), CONVENTIONS_SHA256, RESYNC)

    @unittest.skipIf(
        importlib.util.find_spec("reconciler") is None,
        "willow-reconciler is not installed here (stdlib-only repo); "
        "the hash pin above is the whole guarantee",
    )
    def test_the_vendored_copy_equals_what_the_reconciler_publishes(self):
        from reconciler.conventions import conventions

        self.assertEqual(RULES, conventions())


# ── the real tree ───────────────────────────────────────────────────────────


class ThisTreeMeetsThePublishedConventions(unittest.TestCase):
    def test_pr_title_guard_is_present_wherever_automerge_is_armed(self):
        self.assertTrue(
            _arms_automerge(REPO_ROOT), "release-please.yml is expected to arm auto-merge here"
        )
        self.assertEqual(
            _missing_when_armed(REPO_ROOT, RULES["required_when_release_please_arms_automerge"]), []
        )

    def test_the_configs_hidden_set_equals_the_published_set(self):
        text = (REPO_ROOT / RELEASE_CONFIG).read_text(encoding="utf-8")
        self.assertEqual(_config_hidden_types(text), set(RULES["hidden_types"]))

    def test_the_config_carries_every_required_reasoning_comment(self):
        text = (REPO_ROOT / RELEASE_CONFIG).read_text(encoding="utf-8")
        self.assertEqual(_config_missing_comments(text, RULES["required_config_comments"]), [])

    def test_contributing_names_the_test_command(self):
        self.assertIs(RULES["contributing_must_name_test_command"], True)
        self.assertTrue(_names_test_command((REPO_ROOT / CONTRIBUTING).read_text(encoding="utf-8")))

    def test_trailers_workflow_is_present_because_a_pile_exists(self):
        """`docs/ideas.md` is a numbered pile, so every file the published
        rule requires for one — `trailers.yml`, which runs `reconciler
        verify` — must be present."""
        self.assertTrue((REPO_ROOT / PILE).exists())
        self.assertTrue(
            _pile_is_numbered((REPO_ROOT / PILE).read_text(encoding="utf-8")),
            "the pile the rule binds on must carry ids of the fleet's shape",
        )
        self.assertEqual(
            _missing_when_pile_exists(REPO_ROOT, RULES["required_when_pile_exists"], pile=PILE), []
        )


# ── the plants ──────────────────────────────────────────────────────────────


class ThePlants(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _tree(self, label: str, *, arms: bool, files: tuple[str, ...] = ()) -> Path:
        root = self.tmp / label
        (root / ".github" / "workflows").mkdir(parents=True)
        body = "jobs:\n  release-please:\n    steps:\n      - run: |\n"
        body += f'          {ARMS_AUTOMERGE} "$pr"\n' if arms else "          gh pr list\n"
        (root / RELEASE_PLEASE).write_text(body, encoding="utf-8")
        for f in files:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text("# planted\n", encoding="utf-8")
        return root

    def test_the_armed_tree_check_fires_on_a_planted_tree_missing_the_guard(self):
        required = RULES["required_when_release_please_arms_automerge"]
        self.assertEqual(_missing_when_armed(self._tree("bare", arms=True), required), required)
        self.assertEqual(
            _missing_when_armed(self._tree("guarded", arms=True, files=tuple(required)), required),
            [],
        )
        self.assertEqual(_missing_when_armed(self._tree("manual", arms=False), required), [])

    def test_the_hidden_set_check_catches_a_planted_config_that_unhides_ci(self):
        planted = json.dumps(
            {
                "packages": {
                    ".": {
                        "changelog-sections": [
                            {"type": "feat", "section": "Added"},
                            {"type": "docs", "section": "Docs", "hidden": True},
                            {"type": "test", "section": "Tests", "hidden": True},
                            {"type": "ci", "section": "CI"},
                            {"type": "chore", "section": "Chores", "hidden": True},
                        ],
                        "$comment-what-cuts-a-release": "kept",
                    }
                }
            }
        )
        self.assertEqual(_config_hidden_types(planted), {"chore", "docs", "test"})
        self.assertNotEqual(_config_hidden_types(planted), set(RULES["hidden_types"]))
        self.assertEqual(
            _config_missing_comments(planted, RULES["required_config_comments"]),
            ["$comment-hidden-rule"],
        )

    def test_the_pile_check_fires_on_a_planted_tree_with_a_pile_and_no_verify_gate(self):
        required = RULES["required_when_pile_exists"]
        pile = "docs/ideas.md"
        with_pile = self._tree("pile", arms=False, files=(pile,))
        self.assertEqual(_missing_when_pile_exists(with_pile, required, pile=pile), required)
        gated = self._tree("gated", arms=False, files=(pile, *required))
        self.assertEqual(_missing_when_pile_exists(gated, required, pile=pile), [])
        self.assertEqual(
            _missing_when_pile_exists(with_pile, required, pile=None),
            [],
            "a repo with no numbered pile is not held to the rule",
        )

    def test_the_numbered_pile_read_fires_on_a_planted_item_and_not_on_a_version(self):
        """Planted: a top-level `N. ` item (the parser's own rule) or a
        written-out fleet id is read as numbering; a version number in prose
        — which IDEAS.md is full of — and a nested item are not."""
        self.assertTrue(
            _pile_is_numbered("## A. Near\n\n12. A prose renderer — never more than the numbers.\n")
        )
        self.assertTrue(_pile_is_numbered("Some prose, see willow-ideas-005 for the source.\n"))
        self.assertFalse(_pile_is_numbered("### `corpuslens diff two runs`\n\n*Shipped 0.2.0*.\n"))
        self.assertFalse(_pile_is_numbered("at 0.2.1 it was an unchecked one; 100 events\n"))
        self.assertFalse(_pile_is_numbered("- a bullet\n   1. nested under it\n"))
        self.assertFalse(_pile_is_numbered("12.nospace is a near-miss to the parser too\n"))
        # and the long-form file beside the pile is still not a numbered one
        self.assertFalse(_pile_is_numbered((REPO_ROOT / "IDEAS.md").read_text(encoding="utf-8")))

    def test_the_contributing_check_catches_a_planted_contributing_without_the_command(self):
        self.assertFalse(_names_test_command("# Contributing\n\nRun the tests before pushing.\n"))
        self.assertTrue(_names_test_command(f"```sh\n{TEST_COMMAND}\n```\n"))


if __name__ == "__main__":
    unittest.main()
