"""corpuslens.subject — deriving this run's SUBJECT from an authorship_mix
result this worktree does not build (see corpuslens/subject.py's module
docstring and NOTES-subject.md). `corpuslens/authorship.py` is not part of
this branch, so every test here STUBS the shape `subject.infer_subject`
consumes directly, as a plain dict — never a real classifier.
"""

import unittest

from corpuslens.analyze import SMALL_N
from corpuslens.subject import (
    DOMINANT_FRAC,
    MAX_UNCLASSIFIED_FRAC,
    SUBJECT_AGENT,
    SUBJECT_HUMAN,
    SUBJECT_MIXED,
    SUBJECT_UNKNOWN,
    infer_subject,
)


def _mix(n, human_pct=0.0, agent_pct=0.0, unknown_pct=0.0):
    return {
        "authorship_mix": {
            "n": n,
            "human_pct": human_pct,
            "agent_pct": agent_pct,
            "unknown_pct": unknown_pct,
        }
    }


class MissingEvidenceTests(unittest.TestCase):
    def test_no_authorship_mix_key_at_all_is_unknown(self):
        subj, reason = infer_subject({"steering_density": {"headline": "h"}})
        self.assertEqual(subj, SUBJECT_UNKNOWN)
        self.assertIn("not registered", reason)

    def test_empty_results_is_unknown(self):
        subj, reason = infer_subject({})
        self.assertEqual(subj, SUBJECT_UNKNOWN)

    def test_authorship_mix_error_result_is_unknown(self):
        subj, reason = infer_subject({"authorship_mix": {"error": "no operator turns"}})
        self.assertEqual(subj, SUBJECT_UNKNOWN)
        self.assertIn("no operator turns", reason)

    def test_zero_classified_turns_is_unknown(self):
        subj, reason = infer_subject(_mix(0, human_pct=100.0))
        self.assertEqual(subj, SUBJECT_UNKNOWN)

    def test_too_few_supporting_turns_is_unknown(self):
        # the floor is on turns SUPPORTING the leading class, not corpus size
        subj, reason = infer_subject(_mix(10, human_pct=100.0))
        self.assertEqual(subj, SUBJECT_UNKNOWN)
        self.assertIn("support the leading class", reason)

    def test_a_unanimous_call_is_not_refused_for_being_under_small_n(self):
        """The regression this rule was changed for.

        The floor used to be corpus size borrowed from SMALL_N, which exists so
        a PERCENTAGE is not read to a decimal on a thin sample — a different
        question from whether a two-way categorical call is supported. Under
        that rule this project's own corpus, 24 of 24 unanimously human,
        returned 'undetermined', while a 30-turn corpus split 24/6 did not.
        """
        subj, _ = infer_subject(_mix(24, human_pct=100.0))
        self.assertEqual(subj, SUBJECT_HUMAN)

    def test_the_rule_never_refuses_strictly_stronger_evidence(self):
        """The invariant the old floor broke, pinned directly.

        If some (n, leading share) yields a categorical call, then any case
        with at least as many supporting turns AND at least as high a share
        must also yield one. A rule that fails this is rejecting evidence it
        would accept in a weaker form, which is what a corpus-size floor does
        to a unanimous result.
        """
        cases = [(n, pct) for n in (10, 20, 24, 30, 60, 200) for pct in (80.0, 90.0, 100.0)]
        decided = {
            (n, pct): infer_subject(_mix(n, human_pct=pct))[0] != SUBJECT_UNKNOWN
            for n, pct in cases
        }
        for (n1, p1), ok1 in decided.items():
            if not ok1:
                continue
            support1 = n1 * p1
            for (n2, p2), ok2 in decided.items():
                if n2 * p2 >= support1 and p2 >= p1:
                    self.assertTrue(ok2, f"({n2},{p2}) refused but ({n1},{p1}) accepted")

    def test_at_small_n_with_a_dominant_class_is_not_unknown(self):
        subj, _ = infer_subject(_mix(SMALL_N, human_pct=100.0))
        self.assertEqual(subj, SUBJECT_HUMAN)

    def test_too_much_unclassified_mass_is_unknown_regardless_of_the_split(self):
        # 60% agent of the CLASSIFIED share would clear DOMINANT_FRAC on its
        # own, but more than half of all turns landed in unknown -- the
        # classified remainder is not trustworthy evidence on its own.
        subj, reason = infer_subject(_mix(100, human_pct=20.0, agent_pct=30.0, unknown_pct=50.1))
        self.assertEqual(subj, SUBJECT_UNKNOWN)
        self.assertIn("50.1%", reason)


class PredominantCallTests(unittest.TestCase):
    def test_predominantly_human(self):
        subj, reason = infer_subject(_mix(200, human_pct=96.8, agent_pct=1.0, unknown_pct=2.2))
        self.assertEqual(subj, SUBJECT_HUMAN)
        self.assertIn("96.8%", reason)

    def test_predominantly_agent_the_swe_agent_case(self):
        # the motivating example from the task: a SWE-agent trajectory corpus
        # where the "operator" role is filled by the model steering itself.
        subj, reason = infer_subject(_mix(500, human_pct=2.0, agent_pct=88.6, unknown_pct=9.4))
        self.assertEqual(subj, SUBJECT_AGENT)
        self.assertIn("88.6%", reason)

    def test_exactly_at_the_threshold_counts_as_predominant(self):
        pct = DOMINANT_FRAC * 100
        subj, _ = infer_subject(_mix(100, human_pct=pct, agent_pct=0.0, unknown_pct=100 - pct))
        self.assertEqual(subj, SUBJECT_HUMAN)

    def test_just_under_the_threshold_is_mixed_not_human(self):
        pct = DOMINANT_FRAC * 100 - 0.1
        subj, reason = infer_subject(_mix(100, human_pct=pct, agent_pct=100 - pct, unknown_pct=0.0))
        self.assertEqual(subj, SUBJECT_MIXED)
        self.assertIn("mixes both", reason)

    def test_a_60_40_split_is_mixed_never_rounded_to_the_majority_class(self):
        subj, reason = infer_subject(_mix(300, human_pct=60.0, agent_pct=35.0, unknown_pct=5.0))
        self.assertEqual(subj, SUBJECT_MIXED)
        self.assertIn("60.0%", reason)
        self.assertIn("35.0%", reason)

    def test_never_returns_a_value_outside_the_declared_set(self):
        from corpuslens.subject import SUBJECTS

        for human, agent, unk in (
            (100.0, 0.0, 0.0),
            (0.0, 100.0, 0.0),
            (50.0, 50.0, 0.0),
            (0.0, 0.0, 100.0),
            (33.0, 33.0, 34.0),
        ):
            subj, _ = infer_subject(_mix(200, human, agent, unk))
            with self.subTest(human=human, agent=agent, unknown=unk):
                self.assertIn(subj, SUBJECTS)


class ConstantsSanityTests(unittest.TestCase):
    def test_thresholds_are_fractions_not_percentages(self):
        self.assertGreater(DOMINANT_FRAC, 0.5)
        self.assertLessEqual(DOMINANT_FRAC, 1.0)
        self.assertGreater(MAX_UNCLASSIFIED_FRAC, 0.0)
        self.assertLess(MAX_UNCLASSIFIED_FRAC, 1.0)


if __name__ == "__main__":
    unittest.main()
