"""Tests for `corpuslens label` / `corpuslens score` (IDEAS.md, "A local
labelling mode"). The load-bearing rules under test:

  * the label store may contain ONLY {source_ref, classifier, label} entries
    plus a top-level classifier_version — never content, a filename, or a
    timestamp;
  * sampling is fixed-seed and therefore repeatable on the same corpus;
  * a label set is tied to the classifier version it graded, and scoring (or
    labelling more) against a different version is a loud refusal, never a
    silent comparison;
  * a non-tty stdin is refused rather than hung on;
  * the human is the only labeller — nothing here ever infers a label.
"""
import io
import itertools
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from corpuslens import ingest, label as labelmod
from corpuslens.cli import main as cli_main
from corpuslens.classifiers import CLASSIFIER_SET_VERSION
from corpuslens.model import AuthorClass, CoarseTime, DataType, Event, Surface

from test_pipeline import _cc_line, _write


def _leaks_in(raw, terms):
    """Every one of `terms` present in `raw` — the label store's text once
    it has left the wall, against the dates, filenames and turn text that
    must never reach it. The caller decides what must be absent; this only
    reports what got through. Planted in LabelCliTests."""
    return [term for term in terms if term in raw]


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


def _ev(ref, author, dtype, chars=40, features=None):
    f = {"char_count": chars, "word_count": 8}
    if features:
        f.update(features)
    return Event(event_id=ref, corpus_id="c", adapter_id="a", source_ref=ref,
                 thread_id="t", surface=Surface.CLI, author_class=author,
                 data_type=dtype, time=CoarseTime(day_offset=0), features=f)


class CorpusFixture(unittest.TestCase):
    """A small claude-code corpus with a mix of operator/machine turns, some
    matching the classifiers and some not."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        _write(self.d / "s1.jsonl", [
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line("assistant", "Done. Should I add validation, or keep it minimal?", "2026-02-01T10:05:00Z"),
            _cc_line("user", "it still fails on empty input, fix that", "2026-02-01T10:20:00Z"),
            _cc_line("user", "lets talk about options for the cache layer", "2026-02-03T09:00:00Z"),
            _cc_line("assistant", "All 12 tests pass.", "2026-02-03T09:05:00Z"),
        ])
        _write(self.d / "s2.jsonl", [
            _cc_line("user", "what does mastery.py return on line 40?", "2026-02-02T08:00:00Z"),
            _cc_line("assistant", "It returns the posterior.", "2026-02-02T08:01:00Z"),
        ])

    def tearDown(self):
        self.tmp.cleanup()


# ── pure logic (label.py) ────────────────────────────────────────────────────

class EligiblePoolTests(unittest.TestCase):
    def test_pool_is_operator_prompts_and_machine_responses_over_the_char_threshold(self):
        events = [
            _ev("op-long", AuthorClass.OPERATOR, DataType.PROMPT, chars=40),
            _ev("op-short", AuthorClass.OPERATOR, DataType.PROMPT, chars=3),
            _ev("machine-long", AuthorClass.MACHINE, DataType.RESPONSE, chars=40),
            _ev("machine-short", AuthorClass.MACHINE, DataType.RESPONSE, chars=1),
        ]
        pool = {e.source_ref for e in labelmod.eligible_pool(events)}
        self.assertEqual(pool, {"op-long", "machine-long"})

    def test_classifiers_for_author_class(self):
        self.assertEqual(labelmod.classifiers_for(AuthorClass.OPERATOR),
                         ("code_authored", "code_ref", "delib"))
        self.assertEqual(labelmod.classifiers_for(AuthorClass.MACHINE), ("clarify",))
        self.assertEqual(labelmod.classifiers_for(AuthorClass.AGENT), ())


class SamplingTests(unittest.TestCase):
    def test_sampling_is_deterministic_across_two_calls(self):
        events = [_ev(f"r{i}", AuthorClass.OPERATOR, DataType.PROMPT) for i in range(40)]
        s1 = [e.source_ref for e in labelmod.sample_events(events, 10)]
        s2 = [e.source_ref for e in labelmod.sample_events(events, 10)]
        self.assertEqual(s1, s2)

    def test_sampling_is_deterministic_even_if_the_events_list_order_changes(self):
        # sort-by-source_ref before sampling means iteration/insertion order of
        # the caller's list must not change WHICH turns get sampled.
        events = [_ev(f"r{i}", AuthorClass.OPERATOR, DataType.PROMPT) for i in range(40)]
        shuffled = list(reversed(events))
        s1 = [e.source_ref for e in labelmod.sample_events(events, 10)]
        s2 = [e.source_ref for e in labelmod.sample_events(shuffled, 10)]
        self.assertEqual(sorted(s1), sorted(s2))

    def test_sample_caps_at_pool_size(self):
        events = [_ev("only-one", AuthorClass.OPERATOR, DataType.PROMPT)]
        self.assertEqual(len(labelmod.sample_events(events, 50)), 1)

    def test_empty_pool_samples_nothing(self):
        self.assertEqual(labelmod.sample_events([], 50), [])


class StoreTests(unittest.TestCase):
    def test_round_trip_carries_only_the_permitted_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "store.json"
            store = labelmod.empty_store()
            labelmod.add_label(store, "abc123", "code_ref", True)
            labelmod.add_label(store, "abc123", "delib", False)
            labelmod.save_store(p, store)
            raw = json.loads(p.read_text())
            self.assertEqual(set(raw.keys()), {"classifier_version", "labels"})
            for rec in raw["labels"]:
                self.assertEqual(set(rec.keys()), {"source_ref", "classifier", "label"})
            reloaded = labelmod.load_store(p)
            self.assertEqual(reloaded["classifier_version"], CLASSIFIER_SET_VERSION)
            self.assertEqual(len(reloaded["labels"]), 2)

    def test_missing_store_file_is_empty_not_an_error(self):
        store = labelmod.load_store("/nonexistent/path/store.json")
        self.assertIsNone(store["classifier_version"])
        self.assertEqual(store["labels"], [])

    def test_check_version_accepts_empty_and_matching_stores(self):
        self.assertIsNone(labelmod.check_version(labelmod.empty_store()))
        store = {"classifier_version": CLASSIFIER_SET_VERSION, "labels": []}
        self.assertIsNone(labelmod.check_version(store))

    def test_check_version_refuses_a_mismatch_loudly(self):
        store = {"classifier_version": "regex-classifiers/0", "labels": []}
        msg = labelmod.check_version(store)
        self.assertIsNotNone(msg)
        self.assertIn("regex-classifiers/0", msg)
        self.assertIn(CLASSIFIER_SET_VERSION, msg)

    def test_already_labelled_and_add_label(self):
        store = labelmod.empty_store()
        labelmod.add_label(store, "ref1", "clarify", True)
        self.assertEqual(labelmod.already_labelled(store), {("ref1", "clarify")})


class ScoringTests(unittest.TestCase):
    def test_precision_recall_and_n_are_computed_per_classifier(self):
        events = [
            _ev("tp", AuthorClass.OPERATOR, DataType.PROMPT, features={"code_ref": True}),
            _ev("fp", AuthorClass.OPERATOR, DataType.PROMPT, features={"code_ref": True}),
            _ev("fn", AuthorClass.OPERATOR, DataType.PROMPT, features={"code_ref": False}),
            _ev("tn", AuthorClass.OPERATOR, DataType.PROMPT, features={"code_ref": False}),
        ]
        store = labelmod.empty_store()
        labelmod.add_label(store, "tp", "code_ref", True)
        labelmod.add_label(store, "fp", "code_ref", False)
        labelmod.add_label(store, "fn", "code_ref", True)
        labelmod.add_label(store, "tn", "code_ref", False)
        result = labelmod.score(events, store)
        r = result["classifiers"]["code_ref"]
        self.assertEqual((r["tp"], r["fp"], r["fn"], r["tn"]), (1, 1, 1, 1))
        self.assertEqual(r["n"], 4)
        self.assertEqual(r["precision_pct"], 50.0)   # tp / (tp+fp)
        self.assertEqual(r["recall_pct"], 50.0)      # tp / (tp+fn)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["total_labels"], 4)

    def test_a_classifier_that_never_predicts_positive_reports_precision_not_computable(self):
        events = [_ev("r1", AuthorClass.OPERATOR, DataType.PROMPT, features={"delib": False})]
        store = labelmod.empty_store()
        labelmod.add_label(store, "r1", "delib", False)
        r = labelmod.score(events, store)["classifiers"]["delib"]
        self.assertIsNone(r["precision_pct"])
        self.assertIn("precision_note", r)
        self.assertIsNone(r["recall_pct"])            # no positive label either
        self.assertIn("recall_note", r)

    def test_a_labelled_turn_no_longer_in_the_corpus_is_counted_as_missing(self):
        store = labelmod.empty_store()
        labelmod.add_label(store, "gone", "delib", True)
        result = labelmod.score([], store)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["classifiers"], {})

    def test_scoring_never_touches_content_only_the_boolean_feature(self):
        # score() must read the classifier's OWN feature key, never text.
        events = [_ev("r1", AuthorClass.MACHINE, DataType.RESPONSE, features={"clarify": True})]
        store = labelmod.empty_store()
        labelmod.add_label(store, "r1", "clarify", True)
        r = labelmod.score(events, store)["classifiers"]["clarify"]
        self.assertEqual(r["tp"], 1)


# ── the text seam: fixed arity, and the three conditions that keep the
#    ungated hash->content map in `label_text` honest (see its docstring) ───

class LabelTextSeamTests(CorpusFixture):
    """Pins the two structural requirements from the 2026-09-11 audit:

      1. `ingest.get(name)(path, ...)` always returns the same 3-tuple —
         no keyword changes its shape. Turn text comes from a SEPARATE
         function (`ingest.get_label_text`), not a flag on this one.
      2. The three conditions named in `label_text`'s docstring that keep its
         ungated hash->content map honest: text never reaches an `Event`,
         never reaches a renderer/report, and never reaches a label store.
         (The third is also pinned in `LabelCliTests` below, from the other
         direction — via the interactive CLI path.)
    """

    def test_ingest_always_returns_a_plain_three_tuple(self):
        result = ingest.get("claude-code")(str(self.d))
        self.assertEqual(len(result), 3)
        events, quarantine, dropped = result   # must unpack cleanly, unconditionally
        self.assertTrue(events)

    def test_ingest_has_no_flag_that_changes_its_return_shape(self):
        # the exact mistake the audit flagged: an adapter whose arity depends
        # on a keyword. `ingest()` must not accept `with_text` at all anymore.
        with self.assertRaises(TypeError):
            ingest.get("claude-code")(str(self.d), with_text=True)

    def test_label_text_is_a_separate_function_with_its_own_fixed_shape(self):
        lc = ingest.get_label_text("claude-code")(str(self.d))
        self.assertTrue(hasattr(lc, "events"))
        self.assertTrue(hasattr(lc, "quarantine"))
        self.assertTrue(hasattr(lc, "drops"))
        self.assertTrue(hasattr(lc, "text_by_ref"))
        self.assertTrue(lc.text_by_ref)   # this corpus has kept events

    def test_get_label_text_refuses_an_adapter_that_never_registered_one(self):
        with self.assertRaises(KeyError):
            ingest.get_label_text("cursor")

    def test_condition_one_no_event_feature_is_ever_a_string(self):
        # `Event.features` is documented as booleans/counts only. If this ever
        # stops being true, `label_text`'s reasoning (condition 1) is broken.
        lc = ingest.get_label_text("claude-code")(str(self.d))
        for e in lc.events:
            for k, v in e.features.items():
                self.assertNotIsInstance(v, str, f"features[{k!r}] is a string on {e.source_ref}")
        # and the turn text itself never appears in any Event identifier field
        for e in lc.events:
            text = lc.text_by_ref.get(e.source_ref, "")
            for fld in (e.event_id, e.source_ref, e.thread_id):
                if text.strip():
                    self.assertNotIn(text.strip()[:10], fld)

    def test_condition_two_run_and_doctor_never_leak_turn_text(self):
        # label_text is a SEPARATE seam from the one run/doctor use
        # (`_ingest`, which calls `ingest.get`, never `get_label_text`) — this
        # asserts that separation holds at the observable-output level too.
        distinctive = ("build the parser", "cache layer", "mastery.py",
                       "posterior", "All 12 tests pass")
        for argv in (["run", str(self.d), "--adapter", "claude-code"],
                    ["run", str(self.d), "--adapter", "claude-code", "--format", "json"],
                    ["doctor", str(self.d), "--adapter", "claude-code"],
                    ["doctor", str(self.d), "--adapter", "claude-code", "--format", "json"]):
            _, out, _ = _run(argv)
            for leak in distinctive:
                self.assertNotIn(leak, out, f"{leak!r} leaked via {argv}")

    def test_condition_three_label_store_never_carries_turn_text(self):
        # the CLI-level version of this lives in LabelCliTests; this version
        # checks it straight from the source text, not just a few substrings.
        store = self.d / "labels.json"
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "50", "--store", str(store)])
        lc = ingest.get_label_text("claude-code")(str(self.d))
        raw = store.read_text()
        texts = [text.strip() for text in lc.text_by_ref.values() if text.strip()]
        self.assertTrue(texts, "the corpus is expected to carry turn text to check against")
        self.assertEqual(_leaks_in(raw, texts), [])


# ── CLI: `corpuslens label` ─────────────────────────────────────────────────

class LabelCliTests(CorpusFixture):
    def test_non_tty_is_refused_not_hung_on(self):
        store = self.d / "labels.json"
        with mock.patch("sys.stdin.isatty", return_value=False):
            rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                                 "--sample-size", "3", "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("not one", err)
        self.assertFalse(store.exists())

    def test_interactive_session_writes_only_permitted_fields(self):
        store = self.d / "labels.json"
        answers = itertools.cycle(["y", "n"])
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: next(answers)):
            rc, out, _ = _run(["label", str(self.d), "--adapter", "claude-code",
                              "--sample-size", "6", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertTrue(store.exists())
        raw = store.read_text()
        doc = json.loads(raw)
        self.assertEqual(doc["classifier_version"], CLASSIFIER_SET_VERSION)
        self.assertTrue(doc["labels"])
        for rec in doc["labels"]:
            self.assertEqual(set(rec.keys()), {"source_ref", "classifier", "label"})
            self.assertIsInstance(rec["label"], bool)
        # no calendar date, filename, or corpus text ever reaches the store
        self.assertEqual(_leaks_in(raw, ("2026-02-01", "s1.jsonl", "s2.jsonl",
                                         "mastery.py", "config file", "cache layer")), [])
        # but the terminal transcript DID show the turn text (that's the point)
        self.assertIn("build the parser", out)

    def test_planted_leak_in_the_store_is_caught(self):
        # A store that DID carry a filename and a date: both reported, in the
        # caller's order, and the clean term is not.
        store_text = '{"labels": [{"source_ref": "s1.jsonl:3 on 2026-02-01"}]}'
        self.assertEqual(
            _leaks_in(store_text, ("mastery.py", "2026-02-01", "s1.jsonl")),
            ["2026-02-01", "s1.jsonl"],
        )

    def test_rerunning_resumes_rather_than_re_asking(self):
        store = self.d / "labels.json"
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "6", "--store", str(store)])
        before = json.loads(store.read_text())["labels"]
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            rc, out, _ = _run(["label", str(self.d), "--adapter", "claude-code",
                              "--sample-size", "6", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertIn("nothing new to label", out)
        after = json.loads(store.read_text())["labels"]
        self.assertEqual(before, after)   # nothing re-asked, nothing duplicated

    def test_quitting_early_saves_partial_progress(self):
        store = self.d / "labels.json"
        answers = iter(["y", "q"])
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: next(answers)):
            rc, out, _ = _run(["label", str(self.d), "--adapter", "claude-code",
                              "--sample-size", "6", "--store", str(store)])
        self.assertEqual(rc, 0)
        doc = json.loads(store.read_text())
        self.assertEqual(len(doc["labels"]), 1)

    def test_eof_mid_session_is_treated_like_quit_not_a_crash(self):
        store = self.d / "labels.json"
        def raise_eof(prompt):
            raise EOFError
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", raise_eof):
            rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                                 "--sample-size", "6", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_two_fresh_stores_sample_the_same_turns(self):
        # the fixed seed is the whole point: same corpus, same --sample-size,
        # same turns, no matter which store file the labels land in.
        seen = []
        for name in ("a.json", "b.json"):
            store = self.d / name
            with mock.patch("sys.stdin.isatty", return_value=True), \
                 mock.patch("builtins.input", lambda prompt: "y"):
                _run(["label", str(self.d), "--adapter", "claude-code",
                     "--sample-size", "3", "--store", str(store)])
            seen.append(sorted(r["source_ref"] for r in json.loads(store.read_text())["labels"]))
        self.assertEqual(seen[0], seen[1])

    def test_refuses_an_adapter_that_cannot_show_turn_text(self):
        store = self.d / "labels.json"
        rc, out, err = _run(["label", str(self.d), "--adapter", "cursor",
                             "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("cursor", err)
        self.assertFalse(store.exists())

    def test_refuses_to_extend_a_store_graded_under_a_different_version(self):
        store = self.d / "labels.json"
        store.write_text(json.dumps({"classifier_version": "regex-classifiers/0", "labels": []}))
        rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                             "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("classifier version", err)

    def test_empty_corpus_is_an_error_not_a_hang(self):
        empty = self.d / "empty"
        empty.mkdir()
        rc, out, err = _run(["label", str(empty), "--adapter", "claude-code",
                             "--store", str(self.d / "labels.json")])
        self.assertEqual(rc, 1)


# ── CLI: `corpuslens score` ──────────────────────────────────────────────────

class ScoreCliTests(CorpusFixture):
    def _label_everything(self, store_path, answer="y"):
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: answer):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "50", "--store", str(store_path)])

    def test_no_store_file_is_a_clear_error(self):
        rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code",
                             "--store", str(self.d / "nope.json")])
        self.assertEqual(rc, 1)
        self.assertIn("corpuslens label", err)

    def test_empty_store_is_a_clear_error(self):
        store = self.d / "labels.json"
        store.write_text(json.dumps(labelmod.empty_store()))
        rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code",
                             "--store", str(store)])
        self.assertEqual(rc, 1)

    def test_score_reports_n_precision_recall_per_classifier(self):
        store = self.d / "labels.json"
        self._label_everything(store)
        rc, out, _ = _run(["score", str(self.d), "--adapter", "claude-code",
                           "--store", str(store), "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        for name, r in doc["classifiers"].items():
            self.assertIn("n", r)
            self.assertIn("precision_denominator", r)
            self.assertIn("recall_denominator", r)

    def test_markdown_score_names_denominators_and_never_leaks_the_corpus(self):
        store = self.d / "labels.json"
        self._label_everything(store)
        rc, out, _ = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertIn("out of labelled turns", out)
        for leak in ("2026-02-01", "s1.jsonl", "mastery.py"):
            self.assertNotIn(leak, out)

    def test_refuses_to_score_against_a_mismatched_classifier_version(self):
        store = self.d / "labels.json"
        self._label_everything(store)
        doc = json.loads(store.read_text())
        doc["classifier_version"] = "regex-classifiers/0"
        store.write_text(json.dumps(doc))
        rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("classifier version", err)

    def test_a_labelled_turn_missing_from_a_changed_corpus_is_counted(self):
        store = self.d / "labels.json"
        s = labelmod.empty_store()
        labelmod.add_label(s, "not-a-real-source-ref", "delib", True)
        store.write_text(json.dumps(s))
        rc, out, _ = _run(["score", str(self.d), "--adapter", "claude-code",
                           "--store", str(store), "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["missing"], 1)


if __name__ == "__main__":
    unittest.main()
