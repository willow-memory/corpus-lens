"""Tests for corpuslens.authorship (classify_turn) and the authorship_mix
analyzer that reports on it.

Covers: a marked turn is always AGENT regardless of its features; a short
plain turn is HUMAN; an ambiguous turn is UNKNOWN and specifically NOT AGENT
(the worst error this module can make); and — mirroring the classifier-hash
discipline in tests/test_analyzer_versions.py — that moving either threshold
in corpuslens/authorship.py without a deliberate version bump is a test
failure, not a silent drift.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from corpuslens.analyze import all_analyzers, semantic_hash
from corpuslens.analyze import authorship_mix as authorship_mix_mod
from corpuslens.authorship import (
    AGENT,
    AGENT_MIN_WORDS,
    AUTHORSHIP_VERSION,
    HUMAN,
    HUMAN_MAX_WORDS,
    UNKNOWN,
    classify_turn,
)
from corpuslens.ingest import claude_code as claude_code_ingest
from corpuslens.model import AuthorClass, CoarseTime, DataType, Event, PROCESS_CLAIM_TYPES, Surface

STYLES_CORPUS = pathlib.Path(__file__).resolve().parent.parent / "examples" / "styles-corpus"


def _features(word_count=0, code_ref=False, **kw):
    f = {
        "word_count": word_count, "char_count": word_count * 5, "code_fenced": False,
        "code_authored": False, "code_ref": code_ref, "delib": False, "question": False,
        "clarify": False, "injected_stripped": False,
    }
    f.update(kw)
    return f


class ClassifyTurnTests(unittest.TestCase):
    def test_marked_turn_is_always_agent(self):
        # Features that look exactly like the human sample must not override
        # a deterministic marker — marked_machine wins outright.
        self.assertEqual(
            classify_turn(_features(word_count=3, code_ref=False), marked_machine=True), AGENT)

    def test_marked_turn_is_agent_even_with_no_features_at_all(self):
        self.assertEqual(classify_turn({}, marked_machine=True), AGENT)

    def test_short_plain_turn_is_human(self):
        # word_count=9 is the human sample's own median (n=18).
        self.assertEqual(classify_turn(_features(word_count=9, code_ref=False)), HUMAN)

    def test_human_max_words_boundary_is_inclusive(self):
        self.assertEqual(classify_turn(_features(word_count=HUMAN_MAX_WORDS, code_ref=False)), HUMAN)
        self.assertEqual(
            classify_turn(_features(word_count=HUMAN_MAX_WORDS + 1, code_ref=False)), UNKNOWN)

    def test_ambiguous_turn_is_unknown_and_never_agent(self):
        # Mid-band word count: clears neither bar.
        self.assertEqual(classify_turn(_features(word_count=150, code_ref=False)), UNKNOWN)
        # Long but code-free — the "human pasting a long brief" collapse case
        # authorship.py's own docstring names. Must land UNKNOWN, not AGENT:
        # this is the worst error this module can make, and the conjunction
        # (word_count AND code_ref) exists specifically to prevent it.
        self.assertEqual(classify_turn(_features(word_count=600, code_ref=False)), UNKNOWN)
        # Short but references code — must not be asserted HUMAN either.
        self.assertEqual(classify_turn(_features(word_count=5, code_ref=True)), UNKNOWN)
        # Every case here must specifically avoid AGENT.
        for wc, ref in ((150, False), (600, False), (5, True)):
            with self.subTest(word_count=wc, code_ref=ref):
                self.assertNotEqual(classify_turn(_features(word_count=wc, code_ref=ref)), AGENT)

    def test_long_and_code_referencing_is_agent(self):
        # word_count=500, code_ref=True is inside the agent sample's own
        # observed range (min 453, 100% code_ref).
        self.assertEqual(classify_turn(_features(word_count=500, code_ref=True)), AGENT)

    def test_agent_min_words_boundary_requires_code_ref_too(self):
        self.assertEqual(
            classify_turn(_features(word_count=AGENT_MIN_WORDS, code_ref=True)), AGENT)
        self.assertEqual(
            classify_turn(_features(word_count=AGENT_MIN_WORDS - 1, code_ref=True)), UNKNOWN)
        self.assertEqual(
            classify_turn(_features(word_count=AGENT_MIN_WORDS, code_ref=False)), UNKNOWN)

    def test_marked_machine_defaults_to_false(self):
        # classify_turn(features) alone must behave identically to explicitly
        # passing marked_machine=False.
        self.assertEqual(classify_turn(_features(word_count=9, code_ref=False)),
                          classify_turn(_features(word_count=9, code_ref=False),
                                        marked_machine=False))

    def test_missing_features_default_safely_to_unknown(self):
        # No word_count, no code_ref at all: must not guess.
        self.assertEqual(classify_turn({}), UNKNOWN)

    def test_return_value_is_one_of_the_three_constants(self):
        for wc in (0, 9, 30, 31, 150, 400, 453, 600, 1000):
            for ref in (True, False):
                with self.subTest(word_count=wc, code_ref=ref):
                    self.assertIn(classify_turn(_features(word_count=wc, code_ref=ref)),
                                  (HUMAN, AGENT, UNKNOWN))


class ThresholdVersionDisciplineTests(unittest.TestCase):
    """Mirrors tests/test_analyzer_versions.py's classifier-hash discipline,
    but for authorship.py's own thresholds: moving HUMAN_MAX_WORDS or
    AGENT_MIN_WORDS without a deliberate version bump must fail loudly."""

    def test_pinned_hash_matches_live_thresholds(self):
        live = semantic_hash(str(HUMAN_MAX_WORDS), str(AGENT_MIN_WORDS), AUTHORSHIP_VERSION)
        self.assertEqual(live, authorship_mix_mod._AUTHORSHIP_MIX_HASH)

    def test_moving_human_threshold_breaks_the_pinned_hash(self):
        mutated = semantic_hash(str(HUMAN_MAX_WORDS + 1), str(AGENT_MIN_WORDS), AUTHORSHIP_VERSION)
        self.assertNotEqual(mutated, authorship_mix_mod._AUTHORSHIP_MIX_HASH)

    def test_moving_agent_threshold_breaks_the_pinned_hash(self):
        mutated = semantic_hash(str(HUMAN_MAX_WORDS), str(AGENT_MIN_WORDS - 1), AUTHORSHIP_VERSION)
        self.assertNotEqual(mutated, authorship_mix_mod._AUTHORSHIP_MIX_HASH)

    def test_authorship_mix_declares_nonempty_semantic_inputs(self):
        a = next(a for a in all_analyzers() if a.name == "authorship_mix")
        self.assertTrue(a.semantic_inputs)
        self.assertEqual(a.semantic_hash, authorship_mix_mod._AUTHORSHIP_MIX_HASH)
        self.assertGreaterEqual(a.version, 1)


class ClaimTypeTests(unittest.TestCase):
    def test_authorship_mix_is_a_process_claim_type(self):
        self.assertIn("authorship_mix", PROCESS_CLAIM_TYPES)


def _event(word_count, code_ref, author_class=AuthorClass.OPERATOR,
           data_type=DataType.PROMPT, thread="t1", ref="r0"):
    return Event(event_id=ref, corpus_id="c", adapter_id="test/1", source_ref=ref,
                 thread_id=thread, surface=Surface.CLI, author_class=author_class,
                 data_type=data_type, time=CoarseTime(day_offset=0),
                 features=_features(word_count=word_count, code_ref=code_ref))


class AuthorshipMixAnalyzerTests(unittest.TestCase):
    def test_registered_with_claim_and_named_denominator(self):
        a = next(a for a in all_analyzers() if a.name == "authorship_mix")
        self.assertEqual(a.claims, ("authorship_mix",))
        self.assertTrue(a.denominator and a.denominator.strip())
        self.assertTrue(a.grading_question and a.grading_question.strip())

    def test_reports_share_of_each_class_with_named_denominator(self):
        events = [
            _event(9, False, ref="r1"),      # human
            _event(500, True, ref="r2"),     # agent
            _event(150, False, ref="r3"),    # unknown
        ]
        res = authorship_mix_mod.authorship_mix(events)
        self.assertEqual(res["n"], 3)
        self.assertIn("headline", res)
        self.assertIn("reading", res)
        third = round(100 / 3, 1)
        self.assertAlmostEqual(res["human_pct"], third)
        self.assertAlmostEqual(res["agent_pct"], third)
        self.assertAlmostEqual(res["unknown_pct"], third)
        self.assertEqual(res["human_n"] + res["agent_n"] + res["unknown_n"], 3)

    def test_all_human_corpus(self):
        events = [_event(9, False, ref=f"r{i}") for i in range(5)]
        res = authorship_mix_mod.authorship_mix(events)
        self.assertEqual(res["human_pct"], 100.0)
        self.assertEqual(res["agent_pct"], 0.0)
        self.assertEqual(res["unknown_pct"], 0.0)

    def test_ignores_machine_response_turns(self):
        events = [
            _event(9, False, ref="r1"),
            _event(9, False, author_class=AuthorClass.MACHINE, data_type=DataType.RESPONSE,
                   ref="r2"),
        ]
        res = authorship_mix_mod.authorship_mix(events)
        self.assertEqual(res["n"], 1)

    def test_no_operator_turns_errors(self):
        events = [_event(9, False, author_class=AuthorClass.MACHINE,
                          data_type=DataType.RESPONSE, ref="r1")]
        res = authorship_mix_mod.authorship_mix(events)
        self.assertIn("error", res)


def _persona_true_author_by_text() -> dict:
    """{turn text (stripped) -> true_author} built from the raw session files
    and truth.json in examples/styles-corpus — see that directory's README
    for what the corpus can and cannot tell you about this classifier."""
    truth = json.loads((STYLES_CORPUS / "truth.json").read_text())["turns"]
    by_persona_turn = {(t["persona"], t["turn"]): t["true_author"] for t in truth}
    text_to_author = {}
    for persona_dir in sorted(p for p in STYLES_CORPUS.iterdir() if p.is_dir()):
        persona = persona_dir.name
        recs = [json.loads(line) for line in
                (persona_dir / "session.jsonl").read_text().splitlines() if line.strip()]
        user_recs = [r for r in recs if r.get("type") == "user"]
        for ti, r in enumerate(user_recs):
            blocks = r.get("message", {}).get("content", [])
            text = " ".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
            text_to_author[text.strip()] = by_persona_turn[(persona, ti)]
    return text_to_author


class StylesCorpusFalsifierTests(unittest.TestCase):
    """The falsifier requested alongside `examples/styles-corpus` (see its own
    README): six invented operators written to BREAK this classifier, not
    confirm it — a rambler, a numbered-spec writer, someone who pastes
    tracebacks, a rapid questioner, a second-language speaker, and the
    reverse case, a machine that dispatches in five-word commands.

    This corpus can FALSIFY (a human persona called AGENT here is a real
    defect — see `test_no_human_persona_is_ever_classified_agent` below) and
    CANNOT VALIDATE (every persona was imagined by one author, whose blind
    spots it exists to expose — passing this says nothing about the true
    error rate on real people). For that, run `corpuslens label` and
    `corpuslens score` on a real corpus.
    """

    @classmethod
    def setUpClass(cls):
        if not STYLES_CORPUS.exists():
            raise unittest.SkipTest(
                "examples/styles-corpus not present — rebuild with "
                "`python3 examples/styles-corpus/build.py` or restore it from git")
        cls.text_to_author = _persona_true_author_by_text()
        corpus = claude_code_ingest.label_text(str(STYLES_CORPUS), corpus_id="styles-corpus-test")
        cls.events = corpus.events
        cls.text_by_ref = corpus.text_by_ref

    def _classified(self):
        out = []
        for e in self.events:
            if e.author_class is not AuthorClass.OPERATOR or e.data_type is not DataType.PROMPT:
                continue
            text = self.text_by_ref.get(e.source_ref, "").strip()
            self.assertIn(text, self.text_to_author, f"unmatched event text: {text!r}")
            true_author = self.text_to_author[text]
            out.append((true_author, classify_turn(e.features, marked_machine=False)))
        return out

    def test_no_human_persona_is_ever_classified_agent(self):
        # THE FALSIFIER. Whatever else this classifier gets wrong, it must
        # never call a real person a machine — the asymmetry the whole design
        # in corpuslens/authorship.py rests on. If this fails, the fix is the
        # classifier (a threshold moved to protect these personas), never
        # this test or the corpus: see examples/styles-corpus/README.md.
        classified = self._classified()
        self.assertTrue(classified, "styles-corpus produced no operator-role turns to check")
        for true_author, predicted in classified:
            if true_author == "human":
                with self.subTest(true_author=true_author, predicted=predicted):
                    self.assertNotEqual(predicted, AGENT)

    def test_covers_every_turn_in_truth_json(self):
        # Guards the test itself against silently checking fewer turns than
        # the corpus actually has (a text-matching bug, a dropped record).
        truth = json.loads((STYLES_CORPUS / "truth.json").read_text())["turns"]
        self.assertEqual(len(self._classified()), len(truth))

    def test_terse_dispatcher_agent_is_not_asserted_human_with_certainty(self):
        # Documents the OTHER side of the trade this design makes, so it
        # cannot regress silently: the reverse persona (a real machine that
        # dispatches in five-word commands) is expected to be missed by this
        # feature set — undercounting AGENT is the accepted cost, not a
        # passing grade to chase away. This turns "known false negative" into
        # a pinned fact rather than a surprise on the next threshold change.
        classified = self._classified()
        agent_predictions = {p for a, p in classified if a == "agent"}
        self.assertNotIn(AGENT, agent_predictions,
                          "if this now fires, classify_turn started catching the terse "
                          "dispatcher on word count/code_ref alone — re-check it is not "
                          "ALSO catching a human persona before treating this as progress")


if __name__ == "__main__":
    unittest.main()
