"""signature_plurality — does the operator role show more than one authoring
signature?

THE CONTRACT THIS ANALYZER LEANS ON (`corpuslens/authorship.py` — HUMAN,
AGENT, UNKNOWN, `classify_turn(features, marked_machine)`) is a sibling
deliverable and is not built here. `corpuslens/analyze/signatures.py` falls
back to a minimal, deliberately under-confident stand-in when the real module
is absent (see that module's docstring), and every test below replaces
`classify_turn` with an explicit stub of its own — via
`unittest.mock.patch.object` — that reads a private `_want_label` key this
test file plants in a turn's `features` dict. That is the "stub it in tests"
this module was written against: these tests exercise `signature_plurality`'s
own clustering/refusal logic under KNOWN labels, independent of whichever
`classify_turn` implementation (real, fallback, or this stub) is on the path.
"""

import itertools
import json
import unittest
from unittest import mock

from corpuslens.analyze import SMALL_N, all_analyzers
from corpuslens.analyze import signatures as sig_mod
from corpuslens.model import PROCESS_CLAIM_TYPES, AuthorClass, CoarseTime, DataType, Event, Surface

_ids = itertools.count()


def _turn(word_count, want_label, char_count=None, thread_id="t", day_offset=0, **extra_features):
    """One eligible operator prompt turn. `want_label` is read by the stub
    `classify_turn` installed in each test below — it is NOT a real feature
    any adapter would ever set, only this test file's way of telling the stub
    what `signature_plurality` should be told about this turn."""
    i = next(_ids)
    feats = {
        "word_count": word_count,
        "char_count": char_count if char_count is not None else max(word_count * 5, 12),
        "_want_label": want_label,
    }
    feats.update(extra_features)
    return Event(
        event_id=f"e{i}",
        corpus_id="c",
        adapter_id="test",
        source_ref=f"r{i}",
        thread_id=thread_id,
        surface=Surface.CLI,
        author_class=AuthorClass.OPERATOR,
        data_type=DataType.PROMPT,
        time=CoarseTime(day_offset=day_offset),
        features=feats,
    )


def _stub_classify(features, marked_machine=False):
    return features.get("_want_label", sig_mod.UNKNOWN)


def _run(events):
    with mock.patch.object(sig_mod, "classify_turn", _stub_classify):
        return sig_mod.signature_plurality(events)


class RegistrationTests(unittest.TestCase):
    def test_registered_with_a_process_claim(self):
        by_name = {a.name: a for a in all_analyzers()}
        self.assertIn("signature_plurality", by_name)
        a = by_name["signature_plurality"]
        for claim in a.claims:
            self.assertIn(
                claim,
                PROCESS_CLAIM_TYPES,
                "authoring_plurality must be process-shaped, not a person claim",
            )

    def test_denominator_and_grading_question_are_named(self):
        by_name = {a.name: a for a in all_analyzers()}
        a = by_name["signature_plurality"]
        self.assertTrue(a.denominator.strip())
        self.assertTrue(a.grading_question.strip())


class SmallNRefusalTests(unittest.TestCase):
    def test_below_small_n_refuses_rather_than_reports(self):
        events = [_turn(10, sig_mod.HUMAN) for _ in range(SMALL_N - 1)]
        res = _run(events)
        self.assertIn("error", res)
        self.assertNotIn("signature_count", res)

    def test_all_unknown_refuses_rather_than_guesses(self):
        events = [_turn(10, sig_mod.UNKNOWN) for _ in range(SMALL_N + 5)]
        res = _run(events)
        self.assertIn("error", res)
        self.assertNotIn("signature_count", res)


class SingleSourceTests(unittest.TestCase):
    """The undercount default: one real source must read as one signature,
    not several, no matter how much its turns vary in length."""

    def test_one_uniform_human_source_reports_one_signature(self):
        events = [_turn(wc, sig_mod.HUMAN) for wc in ([3, 4, 5, 40, 80, 150] * 10)][: SMALL_N + 10]
        res = _run(events)
        self.assertEqual(res["signature_count"], 1)
        self.assertEqual(len(res["signatures"]), 1)
        self.assertAlmostEqual(res["signatures"][0]["share_of_turns_pct"], 100.0)

    def test_one_uniform_agent_source_below_split_floor_reports_one(self):
        # All machine-classified, but fewer than the agent-split floor's worth
        # of turns to trust a sub-split — collapses to one signature.
        events = [_turn(200, sig_mod.AGENT) for _ in range(SMALL_N + 1)]
        res = _run(events)
        self.assertEqual(res["signature_count"], 1)

    def test_human_bucket_is_never_split_even_with_bimodal_lengths(self):
        # Two very different length populations, ALL classified HUMAN. If
        # this analyzer ever split on length alone it would report 2 here —
        # that would be distinguishing writers by shape, the exact move this
        # module refuses to make inside the human-classified bucket.
        events = [_turn(2, sig_mod.HUMAN) for _ in range(20)] + [
            _turn(300, sig_mod.HUMAN) for _ in range(20)
        ]
        res = _run(events)
        self.assertEqual(res["signature_count"], 1)


class PluralSourceTests(unittest.TestCase):
    def test_human_plus_small_agent_bucket_reports_two(self):
        events = [_turn(10, sig_mod.HUMAN) for _ in range(25)] + [
            _turn(300, sig_mod.AGENT) for _ in range(25)
        ]
        res = _run(events)
        self.assertEqual(res["signature_count"], 2)

    def test_large_balanced_agent_bucket_splits_into_two(self):
        # No human turns at all: two clearly distinct machine-shaped length
        # populations, each well over the floor share and floor count.
        events = [_turn(2, sig_mod.AGENT) for _ in range(30)] + [
            _turn(300, sig_mod.AGENT) for _ in range(30)
        ]
        res = _run(events)
        self.assertEqual(res["signature_count"], 2)
        bands = {s["typical_length_band"] for s in res["signatures"]}
        self.assertEqual(bands, {"short", "long"})

    def test_small_minority_band_is_merged_away_not_counted(self):
        # 36 short + 4 medium: the medium slice is under BOTH the floor count
        # (5) and the floor share (15%) of the 40-turn agent bucket, so it
        # must be folded into the surviving band rather than becoming a
        # third signature — the undercount rule in the module docstring.
        events = [_turn(2, sig_mod.AGENT) for _ in range(36)] + [
            _turn(20, sig_mod.AGENT) for _ in range(4)
        ]
        res = _run(events)
        self.assertEqual(res["signature_count"], 1)
        self.assertAlmostEqual(res["signatures"][0]["share_of_turns_pct"], 100.0)

    def test_unknown_turns_never_create_a_signature(self):
        events = [_turn(10, sig_mod.HUMAN) for _ in range(20)] + [
            _turn(10, sig_mod.UNKNOWN) for _ in range(20)
        ]
        res = _run(events)
        self.assertEqual(res["signature_count"], 1)
        self.assertEqual(res["unclassified_turns_pct"], 50.0)


class NoAttributionTests(unittest.TestCase):
    """The output must never let a reader map a signature back to a turn,
    thread, or identity — only an opaque index and aggregate shape."""

    def test_signature_entries_carry_only_opaque_shape_fields(self):
        events = [_turn(10, sig_mod.HUMAN) for _ in range(25)] + [
            _turn(300, sig_mod.AGENT) for _ in range(25)
        ]
        res = _run(events)
        for entry in res["signatures"]:
            self.assertEqual(set(entry), {"index", "share_of_turns_pct", "typical_length_band"})
            self.assertIn(entry["typical_length_band"], ("short", "medium", "long"))
            self.assertIsInstance(entry["index"], int)

    def test_no_thread_or_event_id_leaks_into_the_result(self):
        events = [_turn(10, sig_mod.HUMAN, thread_id="thread-alpha") for _ in range(25)] + [
            _turn(300, sig_mod.AGENT, thread_id="thread-beta") for _ in range(25)
        ]
        res = _run(events)
        blob = json.dumps(res, default=str)
        for e in events:
            self.assertNotIn(e.event_id, blob)
        self.assertNotIn("thread-alpha", blob)
        self.assertNotIn("thread-beta", blob)

    def test_output_never_stamps_a_signature_with_the_contract_vocabulary(self):
        # The result may explain the human/agent split in prose (the boundary
        # this module sits on IS about human vs. machine authorship), but no
        # individual `signatures[i]` entry may carry that vocabulary as a
        # value — that would be exactly the per-signature label the task
        # forbids.
        events = [_turn(10, sig_mod.HUMAN) for _ in range(25)] + [
            _turn(300, sig_mod.AGENT) for _ in range(25)
        ]
        res = _run(events)
        for entry in res["signatures"]:
            self.assertNotIn(
                entry["typical_length_band"], (sig_mod.HUMAN, sig_mod.AGENT, sig_mod.UNKNOWN)
            )
            self.assertNotIn("kind", entry)
            self.assertNotIn("label", entry)
            self.assertNotIn("source", entry)

    def test_order_does_not_track_share_or_seniority(self):
        # Two runs with the SAME two bands but opposite majority/minority
        # roles must keep the same band in the same index position — proof
        # the order comes from a fixed key, not from share or discovery order.
        bigger_short = [_turn(2, sig_mod.AGENT) for _ in range(45)] + [
            _turn(300, sig_mod.AGENT) for _ in range(15)
        ]
        bigger_long = [_turn(2, sig_mod.AGENT) for _ in range(15)] + [
            _turn(300, sig_mod.AGENT) for _ in range(45)
        ]
        res_a = _run(bigger_short)
        res_b = _run(bigger_long)
        long_index_a = next(
            s["index"] for s in res_a["signatures"] if s["typical_length_band"] == "long"
        )
        long_index_b = next(
            s["index"] for s in res_b["signatures"] if s["typical_length_band"] == "long"
        )
        self.assertEqual(
            long_index_a,
            long_index_b,
            "the 'long' band's position moved when its share flipped from "
            "minority to majority — order must come from a fixed key, not share",
        )


class FallbackImportTests(unittest.TestCase):
    """The module must import and be usable even before authorship.py lands
    (see the module docstring's `try`/`except ImportError`)."""

    def test_module_exposes_the_contracts_constants(self):
        self.assertTrue(hasattr(sig_mod, "HUMAN"))
        self.assertTrue(hasattr(sig_mod, "AGENT"))
        self.assertTrue(hasattr(sig_mod, "UNKNOWN"))
        self.assertTrue(callable(sig_mod.classify_turn))

    def test_fallback_classifier_never_invents_a_human_label(self):
        # Without a real authorship.py, the safe fallback must not manufacture
        # a HUMAN classification from a bare features dict — that direction
        # of error is the one this project forbids (undercount, never invent).
        self.assertNotEqual(sig_mod.classify_turn({}, marked_machine=False), sig_mod.HUMAN)


if __name__ == "__main__":
    unittest.main()
