"""End-to-end: `corpuslens run` wires `subject.infer_subject()` into the real
audit record and the real rendered report. `corpuslens/authorship.py` does not
exist in this worktree (see NOTES-subject.md), so the `authorship_mix`
analyzer here is a STUB injected via the same
`mock.patch("corpuslens.cli.all_analyzers", ...)` seam
`test_cli_surface.py::test_leaking_analyzer_is_stopped_in_json_too` already
uses for exactly this reason — a fake analyzer standing in for one this
branch does not build.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from corpuslens.analyze import Analyzer, all_analyzers
from test_cli_surface import _run
from test_pipeline import _cc_line, _write


def _corpus_dir():
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name)
    _write(
        d / "s1.jsonl",
        [
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line(
                "assistant",
                "Done. Should I add validation, or keep it minimal?",
                "2026-02-01T10:05:00Z",
            ),
            _cc_line("user", "it still fails on empty input, fix that", "2026-02-01T10:20:00Z"),
        ],
    )
    return tmp, d


def _authorship_stub(result: dict):
    return Analyzer(
        name="authorship_mix",
        claims=("authorship_mix",),
        denominator="operator-role turns",
        version=1,
        grading_question="none of GRADING.md's ten questions — a precondition for "
        "trusting the pronouns in the other nine sections",
        run=lambda events: result,
    )


class NoAuthorshipAnalyzerTests(unittest.TestCase):
    """Subject falls back to `unknown` and says why, whatever the reason.

    Written when `authorship_mix` was not registered at all, because
    `corpuslens/authorship.py` had not landed; the reason then was "not
    registered". It has since landed, so on a tiny corpus the binding reason
    is the small-sample floor instead. Both are the same behaviour — no
    evidence, so no categorical call, and the reason stated in the record —
    and the test now asserts that shape rather than one particular sentence,
    so it keeps testing the contract instead of the wording of one branch."""

    def setUp(self):
        self.tmp, self.d = _corpus_dir()
        self.addCleanup(self.tmp.cleanup)

    def test_subject_defaults_to_unknown_and_says_why(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        doc = json.loads(out)
        self.assertEqual(doc["audit"]["subject"], "unknown")
        reason = doc["audit"]["subject_reason"]
        self.assertTrue(reason and reason.strip(), "an unknown subject must say why")
        # whichever path produced it, the reason names the evidence it lacked
        self.assertTrue(
            any(t in reason for t in ("not registered", "not enough evidence", "below the")),
            f"reason should name the missing evidence, got: {reason!r}",
        )
        self.assertIn("of undetermined authorship", doc["audit"]["sentence"])

    def test_pronouns_are_neutralized_in_the_absence_of_the_classifier(self):
        # the conservative default this branch chooses: with no evidence
        # either way, the report does not assume "you" (= human) by default.
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code"])
        self.assertNotIn("your prompt turns", out)
        self.assertIn("operator role", out.lower())


class StubbedAuthorshipMixTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = _corpus_dir()
        self.addCleanup(self.tmp.cleanup)

    def _run_with_stub(self, result, fmt="json"):
        stub = _authorship_stub(result)
        with mock.patch("corpuslens.cli.all_analyzers", return_value=all_analyzers() + [stub]):
            return _run(["run", str(self.d), "--adapter", "claude-code", "--format", fmt])

    def test_predominantly_agent_result_sets_agent_subject(self):
        rc, out, _ = self._run_with_stub(
            {"n": 60, "human_pct": 2.0, "agent_pct": 88.6, "unknown_pct": 9.4}
        )
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["audit"]["subject"], "agent")
        self.assertIn("88.6%", doc["audit"]["subject_reason"])
        self.assertIn("agent, not human", doc["audit"]["sentence"])
        # the consequence: steering_density's reference to the human N=1
        # director is withheld now that the subject is not human.
        self.assertNotIn("reference", doc["results"]["steering_density"])
        self.assertIn("reference_withheld", doc["results"]["steering_density"])

    def test_predominantly_agent_result_drops_pronouns_in_markdown(self):
        rc, out, _ = self._run_with_stub(
            {"n": 60, "human_pct": 2.0, "agent_pct": 88.6, "unknown_pct": 9.4}, fmt="markdown"
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("your prompt turns", out)
        self.assertNotIn("measured_director", out)
        self.assertIn("Reference withheld", out)

    def test_predominantly_human_result_keeps_pronouns_and_reference(self):
        rc, out, _ = self._run_with_stub(
            {"n": 60, "human_pct": 96.8, "agent_pct": 1.0, "unknown_pct": 2.2}, fmt="markdown"
        )
        self.assertEqual(rc, 0)
        self.assertIn("your prompt turns", out)
        self.assertIn("measured_director", out)

    def test_the_egress_scan_still_runs_over_the_lensed_report(self):
        # the subject lens is a text transform on an already-rendered result
        # set -- it must not become a second, unscanned output door.
        rc, out, err = self._run_with_stub(
            {"n": 60, "human_pct": 2.0, "agent_pct": 88.6, "unknown_pct": 9.4}, fmt="markdown"
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("2026-02-01", out)


if __name__ == "__main__":
    unittest.main()
