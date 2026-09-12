"""The release pipeline's guards agree with each other and with pyproject.

`release-please.yml` arms auto-merge on the release PR, so a release ships
unattended the moment CI is green. That makes the PR *title* a
release-controlling artifact: this repo merges with merge commits, GitHub
writes the title into the merge commit body, and release-please parses that
body alongside the real commits — so a title typed `fix:` over a PR whose
commits are all `ci:` cuts a PyPI version nothing installable justifies.
willow-mcp published 2.1.1 that way; this repo's own first release published
`1.0.0` by a config slip (BUGS.md, "The first release published `1.0.0`"), and
a PyPI version can never be reused. `.github/workflows/pr-title.yml` is the
guard, ported from the fleet, and this module keeps the guard wired:

* wherever a workflow arms auto-merge (`gh pr merge --auto`), `pr-title.yml`
  must exist beside it — the guard is only worth anything on the repos that
  merge unattended;
* the guard's one per-repo constant, `PACKAGED`, must agree with pyproject's
  wheel `packages` — it is the one line in that file that must NOT be copied
  between repos, and a stale copy would call every real release "nothing
  installable changes";
* the hidden set in `release-please-config.json` is exactly
  {chore, ci, docs, test}, and the `$comment-hidden-rule` and
  `$comment-what-cuts-a-release` blocks that explain *why* are present — the
  workflow reads the un-hidden set from that file rather than restating it,
  so the two move together.

Per house rule (a scan that has never fired has not been shown to check
anything): every scan here is planted — a fixture workflow tree that arms
auto-merge with no title guard, a `PACKAGED` copied from another repo, and a
config with `ci` un-hidden — and shown to be caught.

Stdlib only, including the TOML read: the test matrix includes 3.10, which
has no `tomllib`, so the wheel `packages` line is read by a narrow regex
scoped to its own `[tool.hatch.build.targets.wheel]` section rather than by a
TOML parser.
"""
from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
TITLE_GUARD = "pr-title.yml"

#: The exact hidden set. Read back from the config rather than hard-coded in
#: the workflow, which is why the config is what this test pins.
EXPECTED_HIDDEN = frozenset({"chore", "ci", "docs", "test"})

#: The two comment blocks that explain the hidden rule to the next person.
#: The workflow's error text names the hidden types; these name the reason.
REQUIRED_COMMENTS = ("$comment-what-cuts-a-release", "$comment-hidden-rule")

#: `gh pr merge ... --auto` — the one line that makes a release ship without a
#: person looking at the PR. Anchored on the subcommand so a comment that
#: merely *mentions* `--auto` is not an arming.
_ARMS_AUTO_MERGE = re.compile(r"\bgh pr merge\b[^\n]*--auto\b")

#: The per-repo constant inside pr-title.yml's embedded Python.
_PACKAGED_LINE = re.compile(r"^\s*PACKAGED\s*=\s*(\(.*?\))\s*$", re.MULTILINE)


def _auto_merge_without_title_guard(workflows_dir: Path) -> list[str]:
    """Workflow files in `workflows_dir` that arm auto-merge while no
    `pr-title.yml` sits beside them. Empty when the guard is present, or when
    nothing arms auto-merge (a repo that merges by hand has a person reading
    the title)."""
    if (workflows_dir / TITLE_GUARD).exists():
        return []
    return sorted(
        path.name
        for path in workflows_dir.glob("*.yml")
        if _ARMS_AUTO_MERGE.search(path.read_text(encoding="utf-8"))
    )


def _packaged_constant(workflow_text: str) -> tuple[str, ...]:
    """The `PACKAGED = (...)` tuple out of pr-title.yml's embedded script."""
    match = _PACKAGED_LINE.search(workflow_text)
    if match is None:
        raise AssertionError("pr-title.yml carries no `PACKAGED = (...)` line")
    return tuple(ast.literal_eval(match.group(1)))


def _toml_section(text: str, header: str) -> str:
    """The lines of one `[header]` table, up to the next table header. A
    narrow stand-in for a TOML parser, which 3.10 does not ship."""
    match = re.search(
        r"^\[" + re.escape(header) + r"\]\n(.*?)(?=^\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _wheel_packages(pyproject_text: str) -> list[str]:
    """pyproject's `[tool.hatch.build.targets.wheel] packages = [...]`."""
    section = _toml_section(pyproject_text, "tool.hatch.build.targets.wheel")
    match = re.search(r"^packages\s*=\s*(\[.*?\])", section, re.MULTILINE)
    if match is None:
        raise AssertionError("pyproject.toml declares no wheel `packages`")
    return list(ast.literal_eval(match.group(1)))


def _packaged_disagreements(packaged: tuple[str, ...], wheel: list[str]) -> list[str]:
    """Every directory `PACKAGED` names that pyproject does not package, and
    every packaged directory `PACKAGED` omits. The directory entries are the
    ones ending in "/"; `pyproject.toml` itself is packaged by construction
    and is not a directory."""
    dirs = {entry for entry in packaged if entry.endswith("/")}
    expected = {f"{pkg}/" for pkg in wheel}
    return sorted(
        [f"PACKAGED names {d!r}, pyproject does not package it" for d in dirs - expected]
        + [f"pyproject packages {d!r}, PACKAGED omits it" for d in expected - dirs]
    )


def _hidden_types(config: dict) -> frozenset[str]:
    """The conventional-commit types the config hides from the changelog —
    and therefore from cutting a release."""
    sections = config["packages"]["."]["changelog-sections"]
    return frozenset(s["type"] for s in sections if s.get("hidden"))


class TitleGuardIsWiredWhereAutoMergeIsArmed(unittest.TestCase):
    """`pr-title.yml` exists wherever a workflow arms auto-merge."""

    def test_this_repo_arms_auto_merge_and_carries_the_guard(self):
        self.assertTrue(
            _ARMS_AUTO_MERGE.search(
                (WORKFLOWS / "release-please.yml").read_text(encoding="utf-8")),
            "release-please.yml is expected to arm auto-merge; if that changed, "
            "this whole module's premise changed with it",
        )
        self.assertEqual(_auto_merge_without_title_guard(WORKFLOWS), [])

    def test_planted_workflow_tree_arming_auto_merge_without_the_guard_is_reported(self):
        """Planted: a workflows directory whose release workflow arms
        auto-merge and has no pr-title.yml beside it — this repo the day
        before this commit. Adding the guard file clears it, and a tree that
        merges by hand was never an offender."""
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp)
            (workflows / "release-please.yml").write_text(
                'run: |\n  gh pr merge --auto --merge "$pr" --repo "$REPO"\n',
                encoding="utf-8",
            )
            (workflows / "tests.yml").write_text("run: python -m unittest\n", encoding="utf-8")
            self.assertEqual(_auto_merge_without_title_guard(workflows),
                             ["release-please.yml"])

            (workflows / TITLE_GUARD).write_text("name: PR title\n", encoding="utf-8")
            self.assertEqual(_auto_merge_without_title_guard(workflows), [])

        with tempfile.TemporaryDirectory() as tmp:
            by_hand = Path(tmp)
            (by_hand / "release-please.yml").write_text(
                "# a person merges the release PR; nothing here says --auto\n",
                encoding="utf-8",
            )
            self.assertEqual(_auto_merge_without_title_guard(by_hand), [])


class PackagedConstantAgreesWithPyproject(unittest.TestCase):
    """`PACKAGED` in pr-title.yml names exactly what pyproject packages."""

    def test_packaged_matches_the_wheel_packages(self):
        packaged = _packaged_constant((WORKFLOWS / TITLE_GUARD).read_text(encoding="utf-8"))
        wheel = _wheel_packages((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(wheel, ["corpuslens"])   # the import package, per pyproject
        self.assertIn("pyproject.toml", packaged)  # a packaging change is a release
        self.assertEqual(_packaged_disagreements(packaged, wheel), [])

    def test_planted_packaged_copied_from_another_repo_is_caught(self):
        """Planted: the constant as kartikeya carries it, pasted here
        unchanged — the one line the fleet's copy of this workflow must not
        share. Against this pyproject it disagrees both ways."""
        pasted = _packaged_constant(
            'run: |\n  python - <<\'PY\'\n'
            '  PACKAGED = ("src/kartikeya/", "pyproject.toml")\n  PY\n'
        )
        self.assertEqual(pasted, ("src/kartikeya/", "pyproject.toml"))
        self.assertEqual(
            _packaged_disagreements(pasted, ["corpuslens"]),
            ["PACKAGED names 'src/kartikeya/', pyproject does not package it",
             "pyproject packages 'corpuslens/', PACKAGED omits it"],
        )

    def test_planted_wheel_section_read_stays_inside_its_own_table(self):
        """Planted: a pyproject whose `packages` line lives in a *different*
        table. The section read must not pick it up, or the check would pass
        on a pyproject that packages nothing under the wheel target."""
        elsewhere = (
            '[tool.hatch.build.targets.sdist]\npackages = ["corpuslens"]\n\n'
            '[tool.hatch.build.targets.wheel]\nexclude = ["tests"]\n'
        )
        with self.assertRaises(AssertionError):
            _wheel_packages(elsewhere)
        here = (
            '[tool.hatch.build.targets.wheel]\n# the import name\n'
            'packages = ["corpuslens"]\n\n[tool.other]\npackages = ["nope"]\n'
        )
        self.assertEqual(_wheel_packages(here), ["corpuslens"])


class HiddenSetIsExactlyWhatTheGuardAssumes(unittest.TestCase):
    """The workflow reads the un-hidden set from the config; the config's
    hidden set is pinned here, with the comments that explain it."""

    def _config(self):
        return json.loads((REPO / "release-please-config.json").read_text(encoding="utf-8"))

    def test_hidden_types_are_exactly_chore_ci_docs_test(self):
        self.assertEqual(_hidden_types(self._config()), EXPECTED_HIDDEN)

    def test_the_hidden_rule_is_written_down_beside_the_sections(self):
        package = self._config()["packages"]["."]
        for key in REQUIRED_COMMENTS:
            self.assertIn(key, package)
        self.assertIn("pip install willow-corpus-lens", package["$comment-hidden-rule"])

    def test_planted_unhiding_ci_is_caught(self):
        """Planted: `ci` un-hidden — the exact slip that published jeles
        v0.4.1 for a workflow change."""
        config = self._config()
        for section in config["packages"]["."]["changelog-sections"]:
            if section["type"] == "ci":
                del section["hidden"]
        self.assertNotEqual(_hidden_types(config), EXPECTED_HIDDEN)
        self.assertEqual(EXPECTED_HIDDEN - _hidden_types(config), {"ci"})


if __name__ == "__main__":
    unittest.main()
