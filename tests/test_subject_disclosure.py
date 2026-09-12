"""The consequence of corpuslens.subject: the audit sentence states the
believed subject (guard.py), and the report's pronouns and reference points
follow it (render.py) — see IDEAS.md, "The harder finding: 'operator' was not
a person, and nothing noticed".

No real `corpuslens.authorship` classifier exists in this worktree, so every
test here either sets `AuditRecord.subject`/`.subject_reason` directly (the
shape `cli.run()` produces once `subject.infer_subject()` derives it) or
stubs an `authorship_mix` result inline — never a real classification.
"""

import unittest

from corpuslens.guard import AuditRecord
from corpuslens.render import markdown


def _audit(subject=None, reason=None, **kw):
    a = AuditRecord(profile="default", **kw)
    a.subject = subject
    a.subject_reason = reason
    return a


class AuditSentenceStatesTheSubjectTests(unittest.TestCase):
    def test_no_subject_set_adds_no_clause(self):
        # backward compatibility: every AuditRecord this project's own tests
        # construct directly never sets `subject`, and their sentence must
        # read exactly as it did before this feature existed.
        a = AuditRecord(profile="default", n_events=5)
        s = a.sentence()
        self.assertNotIn("authorship classifier", s)

    def test_human_subject_is_named_and_hedged(self):
        a = _audit(
            subject="human",
            reason="96.8% of 500 classified operator-role turns "
            "read as human (>= the 80% threshold)",
        )
        s = a.sentence()
        self.assertIn("reads the operator-role turns as human", s)
        self.assertIn("96.8%", s)
        self.assertIn("can be wrong", s)  # the disclosure that survives a wrong classifier

    def test_agent_subject_says_not_human(self):
        a = _audit(
            subject="agent",
            reason="88.6% of 500 classified operator-role turns "
            "read as agent (>= the 80% threshold)",
        )
        s = a.sentence()
        self.assertIn("agent, not human", s)
        self.assertIn("can be wrong", s)

    def test_mixed_subject_says_neither_a_single_human(self):
        a = _audit(subject="mixed", reason="neither class reaches the 80% threshold")
        s = a.sentence()
        self.assertIn("not one human", s)

    def test_unknown_subject_names_the_uncertainty_not_a_guess(self):
        a = _audit(
            subject="unknown",
            reason="only 4 operator-role turn(s) were classified — not enough evidence",
        )
        s = a.sentence()
        self.assertIn("of undetermined authorship", s)
        self.assertIn("only 4 operator-role turn(s)", s)
        self.assertIn("not enough evidence", s)

    def test_subject_clause_appears_in_as_dict_too(self):
        a = _audit(subject="agent", reason="r")
        d = a.as_dict()
        self.assertEqual(d["subject"], "agent")
        self.assertEqual(d["subject_reason"], "r")
        self.assertIn("agent, not human", d["sentence"])

    def test_missing_reason_does_not_crash(self):
        a = _audit(subject="unknown", reason=None)
        s = a.sentence()
        self.assertIn("no reason recorded", s)


class RenderPronounFollowsSubjectTests(unittest.TestCase):
    """render.py's `_apply_subject_lens`, exercised through the public
    `render()` entry point (the seam `cli.run()` actually calls)."""

    def _results(self):
        return {
            "steering_density": {
                "headline": "88.6% of your prompt turns arrive mid-task rather than in a "
                "session's opening prompt.",
                "n": 500,
                "denominator": "operator prompt turns",
                "reference": {
                    "measured_director": "96.8% mid-task, 26-turn work sessions",
                    "swe_bench_tau_bench": "0% mid-task by construction",
                },
            },
            "composition_mix": {
                "headline": "You authored code in 6.3% of your prompts.",
                "reading": "above the coding population = you bring the code to the machine.",
                "n": 200,
                "denominator": "operator prompt turns",
                "reference": {"wildchat_coding_population": {"authored_pct": 14.5}},
            },
        }

    def test_human_subject_leaves_pronouns_alone(self):
        from corpuslens.render import render

        a = _audit_helper("human")
        md = render("markdown", self._results(), a)
        self.assertIn("your prompt turns", md)
        self.assertIn("You authored code", md)
        self.assertIn("measured_director", md)

    def test_no_subject_leaves_pronouns_alone(self):
        from corpuslens.render import render

        a = _audit_helper(None)
        md = render("markdown", self._results(), a)
        self.assertIn("your prompt turns", md)

    def test_agent_subject_drops_the_pronoun(self):
        from corpuslens.render import render

        a = _audit_helper("agent", reason="88.6% agent")
        md = render("markdown", self._results(), a)
        self.assertNotIn("your prompt turns", md)
        self.assertNotIn("You authored code", md)
        self.assertIn("the operator role", md.lower())

    def test_mixed_subject_drops_the_pronoun_too(self):
        from corpuslens.render import render

        a = _audit_helper("mixed", reason="60/40 split")
        md = render("markdown", self._results(), a)
        self.assertNotIn("your prompt turns", md)

    def test_unknown_subject_drops_the_pronoun_too(self):
        # the conservative call: "we don't know" must not silently default to
        # "you" (= assumed human), which would be today's bug wearing a
        # different name.
        from corpuslens.render import render

        a = _audit_helper("unknown", reason="not enough evidence")
        md = render("markdown", self._results(), a)
        self.assertNotIn("your prompt turns", md)

    def test_agent_subject_withholds_every_reference_block(self):
        from corpuslens.render import render

        a = _audit_helper("agent", reason="88.6% agent")
        md = render("markdown", self._results(), a)
        self.assertNotIn("measured_director", md)
        self.assertNotIn("wildchat_coding_population", md)
        self.assertIn("Reference withheld", md)
        self.assertIn("no comparable reference exists for this subject", md.lower())

    def test_json_report_carries_the_same_withholding(self):
        from corpuslens.render import render
        import json

        a = _audit_helper("agent", reason="88.6% agent")
        doc = json.loads(render("json", self._results(), a))
        sd = doc["results"]["steering_density"]
        self.assertNotIn("reference", sd)
        self.assertIn("reference_withheld", sd)
        self.assertNotIn("your", sd["headline"].lower().split())

    def test_direct_markdown_call_is_unaffected_by_the_lens(self):
        # markdown()/json_report() called directly (as most of this project's
        # own render tests do) never had a subject to react to, and must not
        # change shape now that `render()` wraps them.
        a = _audit_helper("agent", reason="x")
        md = markdown(self._results(), a)
        # direct calls bypass the lens entirely -- the seam is `render()`.
        self.assertIn("your prompt turns", md)

    def test_error_result_is_untouched_by_the_lens(self):
        from corpuslens.render import render

        a = _audit_helper("agent", reason="x")
        results = {
            "composition_mix": {"error": "no operator prompts found", "denominator": "turns"}
        }
        md = render("markdown", results, a)
        self.assertIn("no operator prompts found", md)


def _audit_helper(subject, reason=None):
    a = AuditRecord(profile="default", n_events=10)
    a.subject = subject
    a.subject_reason = reason
    return a


if __name__ == "__main__":
    unittest.main()
