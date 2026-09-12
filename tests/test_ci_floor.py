"""The fleet CI floor (fleet plan decision 5), held in place structurally.

`.github/workflows/tests.yml` is the floor: a Linux matrix over every Python
minor pyproject's classifiers declare, a Windows leg on that list's floor and
ceiling, ruff at an exact pinned release, and an aggregate `test` gate that
branch protection requires and that is green only when every leg's result is
exactly `success`. Each of those is a claim a reader would otherwise check by
eye, and every one of them has a way to drift quietly:

* a classifier added to pyproject without a matrix entry, or the reverse —
  the two lists are read from their files and asserted equal;
* a ruff pin loosened to `>=`, or dropped — the install line is read and must
  carry an exact `==X.Y.Z`;
* the gate losing `if: always()`, a leg missing from its `needs:`, or a leg
  whose result is never checked — then a skipped or cancelled leg reads as
  green to the one check branch protection trusts (observed on
  willows-grove#5, as `tests.yml`'s own comment records).

The workflow is read with narrow regexes rather than a YAML parser: this
repo is stdlib-only, tests included, and each question here is about one
line's shape. Job blocks are cut on the two-space-indented `name:` lines
under `jobs:`, which is how every workflow in this tree is laid out.

Every scan is planted in this file: a helper that reads a file and reports
on it is shown to report on a fixture built to violate it (the house rule
`tests/test_scans_fire.py` enforces).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
TESTS_YML = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: The aggregate gate's name — what branch protection requires, fleet-wide.
GATE = "test"

_CLASSIFIER_MINOR = re.compile(r'"Programming Language :: Python :: 3\.(\d+)"')
_REQUIRES_PYTHON = re.compile(r'^requires-python\s*=\s*">=\s*3\.(\d+)"', re.MULTILINE)
_JOB_HEADER = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)
_MATRIX_VERSIONS = re.compile(r"python-version:\s*\[([^\]]*)\]")
_RUFF_INSTALL = re.compile(r"pip install\s+ruff(==|>=|~=|<=|>|<)?([0-9][0-9.]*)?")
_NEEDS = re.compile(r"^\s+needs:\s*\[([^\]]*)\]", re.MULTILINE)
_ALWAYS = re.compile(r"^\s+if:\s*always\(\)\s*$", re.MULTILINE)


def _classifier_minors(pyproject_text: str) -> list[str]:
    """Every `Programming Language :: Python :: 3.X` classifier, as "3.X",
    in the order declared."""
    return [f"3.{m}" for m in _CLASSIFIER_MINOR.findall(pyproject_text)]


def _requires_python_floor(pyproject_text: str) -> str | None:
    match = _REQUIRES_PYTHON.search(pyproject_text)
    return f"3.{match.group(1)}" if match else None


def _job_blocks(workflow_text: str) -> dict[str, str]:
    """{job name: the job's own text}, cut on the two-space-indented headers
    under `jobs:`."""
    jobs_at = workflow_text.find("\njobs:")
    if jobs_at < 0:
        return {}
    body = workflow_text[jobs_at + len("\njobs:") :]
    headers = list(_JOB_HEADER.finditer(body))
    blocks: dict[str, str] = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        blocks[header.group(1)] = body[header.end() : end]
    return blocks


def _matrix_versions(job_text: str) -> list[str]:
    """The `python-version: [...]` list of one job, unquoted, in order."""
    match = _MATRIX_VERSIONS.search(job_text)
    if match is None:
        return []
    return [v.strip().strip("\"'") for v in match.group(1).split(",") if v.strip()]


def _ruff_pin(job_text: str) -> str | None:
    """The exact `ruff==X.Y.Z` a job installs, or None when ruff is not
    installed at all or is installed with any operator but `==`."""
    match = _RUFF_INSTALL.search(job_text)
    if match is None or match.group(1) != "==" or not match.group(2):
        return None
    return match.group(2)


def _gate_defects(workflow_text: str, gate: str = GATE) -> list[str]:
    """Everything wrong with the aggregate gate: absent; not `if: always()`;
    a job it does not `need`; a needed job whose `result != 'success'` is
    never checked. Empty when the gate speaks for every leg."""
    blocks = _job_blocks(workflow_text)
    if gate not in blocks:
        return [f"no job named {gate!r}"]
    text = blocks[gate]
    defects: list[str] = []
    if not _ALWAYS.search(text):
        defects.append(f"{gate} lacks `if: always()`")
    needs_match = _NEEDS.search(text)
    needs = [n.strip() for n in needs_match.group(1).split(",")] if needs_match else []
    for job in blocks:
        if job != gate and job not in needs:
            defects.append(f"{gate} does not need {job}")
    for job in needs:
        if f"needs.{job}.result != 'success'" not in text:
            defects.append(f"{gate} never checks needs.{job}.result != 'success'")
    return defects


# ── the real tree ───────────────────────────────────────────────────────────


class TheMatrixIsTheClassifierList(unittest.TestCase):
    def setUp(self):
        self.pyproject = PYPROJECT.read_text(encoding="utf-8")
        self.jobs = _job_blocks(TESTS_YML.read_text(encoding="utf-8"))

    def test_the_linux_matrix_equals_the_declared_classifiers(self):
        declared = _classifier_minors(self.pyproject)
        self.assertTrue(declared, "pyproject is expected to declare Python minor classifiers")
        self.assertEqual(_matrix_versions(self.jobs["test-matrix"]), declared)

    def test_requires_python_is_the_classifier_floor(self):
        self.assertEqual(
            _requires_python_floor(self.pyproject), _classifier_minors(self.pyproject)[0]
        )

    def test_the_windows_leg_runs_the_floor_and_the_ceiling(self):
        declared = _classifier_minors(self.pyproject)
        self.assertEqual(_matrix_versions(self.jobs["test-windows"]), [declared[0], declared[-1]])
        self.assertIn("windows-latest", self.jobs["test-windows"])


class RuffIsPinned(unittest.TestCase):
    def setUp(self):
        self.lint = _job_blocks(TESTS_YML.read_text(encoding="utf-8"))["lint"]

    def test_ruff_is_installed_at_an_exact_release(self):
        pin = _ruff_pin(self.lint)
        self.assertIsNotNone(pin, "lint must `pip install ruff==X.Y.Z`")
        self.assertRegex(pin, r"^\d+\.\d+\.\d+$")

    def test_lint_runs_both_check_and_format_check(self):
        self.assertIn("ruff check .", self.lint)
        self.assertIn("ruff format --check .", self.lint)


class TheGateSpeaksForEveryLeg(unittest.TestCase):
    def test_the_aggregate_gate_needs_every_job_and_checks_each_result(self):
        self.assertEqual(_gate_defects(TESTS_YML.read_text(encoding="utf-8")), [])


# ── the plants ──────────────────────────────────────────────────────────────

_FLOOR = (
    "name: t\non: push\njobs:\n"
    "  test-matrix:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
    '        python-version: ["3.10", "3.11"]\n'
    "  test-windows:\n    runs-on: windows-latest\n    strategy:\n      matrix:\n"
    '        python-version: ["3.10", "3.11"]\n'
    "  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pip install ruff==1.2.3\n"
    "      - run: ruff check .\n      - run: ruff format --check .\n"
    "  test:\n    needs: [test-matrix, test-windows, lint]\n    if: always()\n"
    "    runs-on: ubuntu-latest\n    steps:\n"
    "      - if: ${{ needs.test-matrix.result != 'success' || needs.test-windows.result != 'success' || needs.lint.result != 'success' }}\n"
    "        run: exit 1\n"
)


class ThePlants(unittest.TestCase):
    def test_the_fixture_floor_is_clean(self):
        """The control: the fixture the plants are cut from has no defect."""
        jobs = _job_blocks(_FLOOR)
        self.assertEqual(sorted(jobs), ["lint", "test", "test-matrix", "test-windows"])
        self.assertEqual(_matrix_versions(jobs["test-matrix"]), ["3.10", "3.11"])
        self.assertEqual(_ruff_pin(jobs["lint"]), "1.2.3")
        self.assertEqual(_gate_defects(_FLOOR), [])

    def test_planted_classifier_drift_is_caught(self):
        """Planted: pyproject declares a minor the matrix does not run, and
        `requires-python` below the first classifier."""
        pyproject = (
            'requires-python = ">=3.9"\nclassifiers = [\n'
            '    "Programming Language :: Python :: 3",\n'
            '    "Programming Language :: Python :: 3.10",\n'
            '    "Programming Language :: Python :: 3.11",\n'
            '    "Programming Language :: Python :: 3.12",\n]\n'
        )
        declared = _classifier_minors(pyproject)
        self.assertEqual(declared, ["3.10", "3.11", "3.12"])
        self.assertNotEqual(_matrix_versions(_job_blocks(_FLOOR)["test-matrix"]), declared)
        self.assertNotEqual(_requires_python_floor(pyproject), declared[0])

    def test_planted_loose_or_missing_ruff_pin_is_caught(self):
        """Planted: `>=`, no version, and no ruff at all — none is a pin."""
        for line in ("pip install ruff>=0.16", "pip install ruff", "pip install build"):
            with self.subTest(line=line):
                self.assertIsNone(_ruff_pin(f"    steps:\n      - run: {line}\n"))

    def test_planted_gate_defects_are_caught_one_by_one(self):
        """Planted: the gate missing, the gate without `if: always()`, a leg
        it does not need, and a needed leg whose result it never checks —
        each named in the report."""
        self.assertEqual(
            _gate_defects(_FLOOR.replace("  test:\n", "  gate:\n")), ["no job named 'test'"]
        )
        self.assertIn(
            "test lacks `if: always()`", _gate_defects(_FLOOR.replace("    if: always()\n", ""))
        )
        self.assertIn(
            "test does not need lint",
            _gate_defects(
                _FLOOR.replace(
                    "needs: [test-matrix, test-windows, lint]", "needs: [test-matrix, test-windows]"
                )
            ),
        )
        self.assertIn(
            "test never checks needs.lint.result != 'success'",
            _gate_defects(_FLOOR.replace(" || needs.lint.result != 'success'", "")),
        )


if __name__ == "__main__":
    unittest.main()
