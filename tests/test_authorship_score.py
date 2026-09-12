"""Tests for the authorship extension to `corpuslens label` / `corpuslens
score` — grading the sibling `corpuslens/authorship.py` classifier (contract:
HUMAN = "human", AGENT = "agent", UNKNOWN = "unknown",
`classify_turn(features, marked_machine=False) -> str`).

That module does not exist in this worktree yet (a sibling agent builds it),
so every test here either:

  * exercises the "not installed" path directly (no stub needed) — this is
    real, not simulated, since the module genuinely is not importable in this
    checkout; or
  * installs a STUB module at `sys.modules["corpuslens.authorship"]` for the
    duration of one test, standing in for the real classifier so label.py's
    scoring/labelling machinery can be graded against the CONTRACT rather
    than against unwritten code. The stub is intentionally simple-minded
    (word-count-threshold plus the marked_machine hint) — it exists to
    produce human/agent/unknown answers with a known, checkable pattern, not
    to resemble a real classifier.

Load-bearing rules under test, mirroring test_label.py's for the four regex
classifiers:

  * the authorship section of the store holds ONLY {source_ref, label}
    (label a STRING, never a bool) plus a top-level authorship_version —
    never content;
  * authorship_version is a SEPARATE axis from classifier_version, checked
    and refused independently;
  * UNKNOWN is scored as a decline, not folded into "wrong": an
    always-UNKNOWN classifier must show 0% recall (not 100% anything) for
    both classes, and "not computable" precision, not a flattering number;
  * "predicted the other class" and "declined" are reported as separate
    counts (fn_wrong vs fn_declined), never merged into one indistinguishable
    fn;
  * when the module is not installed, `label`/`score` for the four regex
    classifiers are completely unaffected (no crash, no behavior change).
"""
import io
import itertools
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from corpuslens import label as labelmod
from corpuslens.cli import main as cli_main
from corpuslens.model import AuthorClass, CoarseTime, DataType, Event, Surface

from test_label import _leaks_in
from test_pipeline import _cc_line, _write


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


def _ev(ref, author, dtype, chars=40, word_count=8, features=None):
    f = {"char_count": chars, "word_count": word_count}
    if features:
        f.update(features)
    return Event(event_id=ref, corpus_id="c", adapter_id="a", source_ref=ref,
                 thread_id="t", surface=Surface.CLI, author_class=author,
                 data_type=dtype, time=CoarseTime(day_offset=0), features=f)


def _make_stub(word_threshold=3):
    """A minimal stand-in for corpuslens.authorship: HUMAN if marked_machine
    is False and the turn is not suspiciously short, AGENT if marked_machine
    is True, UNKNOWN (declines) on a short, unmarked turn. Deterministic and
    simple so test expectations can be computed by hand."""
    mod = types.ModuleType("corpuslens.authorship")
    mod.HUMAN = "human"
    mod.AGENT = "agent"
    mod.UNKNOWN = "unknown"
    mod.AUTHORSHIP_VERSION = "authorship/1"

    def classify_turn(features, marked_machine=False):
        if marked_machine:
            return mod.AGENT
        if features.get("word_count", 0) < word_threshold:
            return mod.UNKNOWN
        return mod.HUMAN

    mod.classify_turn = classify_turn
    return mod


def _always_unknown_stub():
    mod = types.ModuleType("corpuslens.authorship")
    mod.HUMAN, mod.AGENT, mod.UNKNOWN = "human", "agent", "unknown"
    mod.AUTHORSHIP_VERSION = "authorship/1"
    mod.classify_turn = lambda features, marked_machine=False: mod.UNKNOWN
    return mod


class _WithStub:
    """Context manager installing a stub `corpuslens.authorship` module."""

    def __init__(self, mod):
        self.mod = mod
        self._patcher = None

    def __enter__(self):
        import corpuslens
        self._pkg = corpuslens
        self._patcher = mock.patch.dict(sys.modules, {"corpuslens.authorship": self.mod})
        self._patcher.__enter__()
        # Patching sys.modules is not enough once the real module exists: an
        # already-imported `corpuslens.authorship` is also bound as an attribute
        # of the parent package, and `from . import authorship` reads that
        # attribute in preference to the cache. Without this the stub is
        # installed and silently ignored, and the test grades the real
        # classifier while believing it graded the stub.
        self._had_attr = hasattr(corpuslens, "authorship")
        self._saved_attr = getattr(corpuslens, "authorship", None)
        setattr(corpuslens, "authorship", self.mod)
        return self.mod

    def __exit__(self, *a):
        if self._had_attr:
            setattr(self._pkg, "authorship", self._saved_attr)
        else:
            delattr(self._pkg, "authorship")
        self._patcher.__exit__(*a)


class _BlockAuthorshipImport:
    """Make `corpuslens.authorship` genuinely unimportable for a block.

    These tests were written while that module did not exist, and simulated
    its absence by popping it out of `sys.modules`. That worked only while the
    file was missing: once it ships, a pop just clears the cache and the next
    import reads it straight off disk, so the absence was never simulated and
    the defensive path went untested while appearing to pass.

    A meta-path finder that refuses the name is the honest version. It keeps
    `AuthorshipUnavailable` exercised — which still matters, because the
    contract is loaded lazily and a partial install or a vendored subset can
    still hit it.
    """

    class _Blocker:
        def find_module(self, name, path=None):
            return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            if name == "corpuslens.authorship":
                raise ImportError("corpuslens.authorship blocked for this test")
            return None

    def __enter__(self):
        import corpuslens
        self._pkg = corpuslens
        self._saved = sys.modules.pop("corpuslens.authorship", None)
        # `from . import authorship` returns the PARENT PACKAGE'S attribute when
        # one is already bound, without consulting sys.modules or meta_path at
        # all — so clearing the cache alone leaves the import succeeding.
        self._saved_attr = getattr(corpuslens, "authorship", None)
        if self._saved_attr is not None:
            delattr(corpuslens, "authorship")
        self._blocker = self._Blocker()
        sys.meta_path.insert(0, self._blocker)
        return self

    def __exit__(self, *a):
        sys.meta_path.remove(self._blocker)
        if self._saved is not None:
            sys.modules["corpuslens.authorship"] = self._saved
        if self._saved_attr is not None:
            setattr(self._pkg, "authorship", self._saved_attr)


def _block_authorship_for_test(case):
    """Block the import for the rest of `case`, restoring it on cleanup.

    Written as a helper rather than a `with` block because these call sites
    span several statements. Works on 3.10, which has no `enterContext`.
    """
    blocker = _BlockAuthorshipImport()
    blocker.__enter__()
    case.addCleanup(blocker.__exit__, None, None, None)


# ── the contract loader, with the module genuinely blocked ─────

class ContractUnavailableTests(unittest.TestCase):
    def test_authorship_contract_raises_a_clear_error_when_the_module_is_absent(self):
        with _BlockAuthorshipImport(), self.assertRaises(labelmod.AuthorshipUnavailable) as ctx:
            labelmod.authorship_contract()
        self.assertIn("corpuslens/authorship.py", str(ctx.exception))
        self.assertIn("classify_turn", str(ctx.exception))

    def test_authorship_contract_succeeds_once_a_stub_is_installed(self):
        stub = _make_stub()
        with _WithStub(stub):
            mod = labelmod.authorship_contract()
            self.assertIs(mod, stub)


# ── store shape: separate version axis, string label, nothing else ────────

class AuthorshipStoreTests(unittest.TestCase):
    def test_a_store_that_never_touches_authorship_round_trips_unchanged(self):
        # the exact regression this feature must not cause: an old store, or
        # a run that never asks the authorship question, keeps the original
        # two-key shape on disk.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "store.json"
            store = labelmod.empty_store()
            labelmod.add_label(store, "abc", "code_ref", True)
            labelmod.save_store(p, store)
            raw = json.loads(p.read_text())
            self.assertEqual(set(raw.keys()), {"classifier_version", "labels"})

    def test_authorship_round_trip_carries_only_the_permitted_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "store.json"
            store = labelmod.empty_store()
            labelmod.add_authorship_label(store, "abc123", "human", "authorship/1")
            labelmod.add_authorship_label(store, "def456", "agent", "authorship/1")
            labelmod.save_store(p, store)
            raw = json.loads(p.read_text())
            self.assertEqual(raw["authorship_version"], "authorship/1")
            for rec in raw["authorship_labels"]:
                self.assertEqual(set(rec.keys()), {"source_ref", "label"})
                self.assertIsInstance(rec["label"], str)
            reloaded = labelmod.load_store(p)
            self.assertEqual(reloaded["authorship_version"], "authorship/1")
            self.assertEqual(len(reloaded["authorship_labels"]), 2)

    def test_authorship_label_is_never_coerced_to_bool(self):
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "r1", "agent", "authorship/1")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "store.json"
            labelmod.save_store(p, store)
            raw = json.loads(p.read_text())
            self.assertEqual(raw["authorship_labels"][0]["label"], "agent")
            self.assertNotIsInstance(raw["authorship_labels"][0]["label"], bool)

    def test_check_authorship_version_accepts_empty_and_matching_stores(self):
        self.assertIsNone(labelmod.check_authorship_version(labelmod.empty_store(), "authorship/1"))
        store = {"authorship_version": "authorship/1"}
        self.assertIsNone(labelmod.check_authorship_version(store, "authorship/1"))

    def test_check_authorship_version_refuses_a_mismatch_loudly(self):
        store = {"authorship_version": "authorship/0"}
        msg = labelmod.check_authorship_version(store, "authorship/1")
        self.assertIsNotNone(msg)
        self.assertIn("authorship/0", msg)
        self.assertIn("authorship/1", msg)

    def test_authorship_version_is_independent_of_classifier_version(self):
        # a mismatch on one axis must not be reported as, or confused with,
        # the other axis's own version string.
        store = labelmod.empty_store()
        labelmod.add_label(store, "r1", "code_ref", True)  # classifier_version set
        labelmod.add_authorship_label(store, "r1", "human", "authorship/1")
        self.assertIsNone(labelmod.check_version(store))
        self.assertIsNone(labelmod.check_authorship_version(store, "authorship/1"))
        bad_classifier_msg = labelmod.check_version(store, current="regex-classifiers/99")
        self.assertNotIn("authorship", bad_classifier_msg)
        bad_authorship_msg = labelmod.check_authorship_version(store, "authorship/99")
        self.assertNotIn("regex-classifiers", bad_authorship_msg)

    def test_already_labelled_authorship(self):
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "r1", "human", "authorship/1")
        self.assertEqual(labelmod.already_labelled_authorship(store), {"r1"})


# ── scoring: three-valued, unknown as decline, fn split ────────────────────

class AuthorshipScoringTests(unittest.TestCase):
    def test_score_authorship_returns_none_when_the_store_has_no_authorship_labels(self):
        store = labelmod.empty_store()
        labelmod.add_label(store, "r1", "code_ref", True)  # a regex label, not authorship
        self.assertIsNone(labelmod.score_authorship([], store))

    def test_score_authorship_raises_when_the_module_is_unavailable_but_labels_exist(self):
        _block_authorship_for_test(self)
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "r1", "human", "authorship/1")
        with self.assertRaises(labelmod.AuthorshipUnavailable):
            labelmod.score_authorship([], store)

    def test_per_class_precision_recall_with_a_mix_of_correct_wrong_and_declined(self):
        # 4 human-labelled turns, 4 agent-labelled turns; classify_turn is the
        # stub: marked_machine -> agent, word_count<3 -> unknown, else human.
        events = [
            _ev("h-correct", AuthorClass.OPERATOR, DataType.PROMPT, word_count=10),   # -> human
            _ev("h-wrong", AuthorClass.MACHINE, DataType.RESPONSE, word_count=10),     # -> agent (marked)
            _ev("h-declined", AuthorClass.OPERATOR, DataType.PROMPT, word_count=1),    # -> unknown
            _ev("h-correct-2", AuthorClass.OPERATOR, DataType.PROMPT, word_count=10),  # -> human
            _ev("a-correct", AuthorClass.MACHINE, DataType.RESPONSE, word_count=10),   # -> agent (marked)
            _ev("a-wrong", AuthorClass.OPERATOR, DataType.PROMPT, word_count=10),      # -> human
            _ev("a-declined", AuthorClass.OPERATOR, DataType.PROMPT, word_count=1),    # -> unknown (NOT marked machine)
        ]
        store = labelmod.empty_store()
        for ref, label in [("h-correct", "human"), ("h-wrong", "human"),
                           ("h-declined", "human"), ("h-correct-2", "human"),
                           ("a-correct", "agent"), ("a-wrong", "agent"),
                           ("a-declined", "agent")]:
            labelmod.add_authorship_label(store, ref, label, "authorship/1")

        with _WithStub(_make_stub(word_threshold=3)):
            result = labelmod.score_authorship(events, store)

        self.assertEqual(result["n"], 7)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["total_labels"], 7)
        # unknown coverage: h-declined and a-declined both predicted unknown
        self.assertEqual(result["unknown_n"], 2)
        self.assertAlmostEqual(result["unknown_pct"], 100 * 2 / 7, places=1)

        human = result["human"]
        # true positives: h-correct, h-correct-2 -> tp=2
        # false positives (true agent, predicted human): a-wrong -> fp=1
        # false negatives (true human, not predicted human): h-wrong (predicted
        # agent) and h-declined (predicted unknown) -> fn=2, split 1/1
        self.assertEqual(human["tp"], 2)
        self.assertEqual(human["fp"], 1)
        self.assertEqual(human["fn"], 2)
        self.assertEqual(human["fn_wrong"], 1)     # h-wrong: predicted agent
        self.assertEqual(human["fn_declined"], 1)  # h-declined: predicted unknown
        self.assertAlmostEqual(human["precision_pct"], 100 * 2 / 3, places=1)
        self.assertAlmostEqual(human["recall_pct"], 100 * 2 / 4, places=1)

        agent = result["agent"]
        # true positives: a-correct -> tp=1
        # false positives (true human, predicted agent): h-wrong -> fp=1
        # false negatives (true agent, not predicted agent): a-wrong (predicted
        # human) and a-declined (predicted unknown) -> fn=2, split 1/1
        self.assertEqual(agent["tp"], 1)
        self.assertEqual(agent["fp"], 1)
        self.assertEqual(agent["fn"], 2)
        self.assertEqual(agent["fn_wrong"], 1)
        self.assertEqual(agent["fn_declined"], 1)
        self.assertAlmostEqual(agent["precision_pct"], 50.0, places=1)
        self.assertAlmostEqual(agent["recall_pct"], 100 * 1 / 3, places=1)

    def test_always_unknown_classifier_is_scored_as_useless_not_flattering(self):
        # THE central requirement: a classifier that declines on every turn
        # must show 0% recall (not 100%) for both classes, and "not
        # computable" precision (it never committed to a positive answer).
        events = [
            _ev("r1", AuthorClass.OPERATOR, DataType.PROMPT, word_count=10),
            _ev("r2", AuthorClass.MACHINE, DataType.RESPONSE, word_count=10),
        ]
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "r1", "human", "authorship/1")
        labelmod.add_authorship_label(store, "r2", "agent", "authorship/1")

        with _WithStub(_always_unknown_stub()):
            result = labelmod.score_authorship(events, store)

        self.assertEqual(result["unknown_pct"], 100.0)
        for cls in ("human", "agent"):
            self.assertIsNone(result[cls]["precision_pct"])
            self.assertIn("precision_note", result[cls])
            self.assertEqual(result[cls]["recall_pct"], 0.0)   # NOT None, NOT 100 — genuinely 0
            self.assertEqual(result[cls]["fn_declined"], 1)
            self.assertEqual(result[cls]["fn_wrong"], 0)

    def test_a_labelled_turn_missing_from_the_corpus_is_counted_not_dropped(self):
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "gone", "human", "authorship/1")
        with _WithStub(_make_stub()):
            result = labelmod.score_authorship([], store)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["n"], 0)
        self.assertIn("unknown_note", result)

    def test_marked_machine_is_derived_from_the_events_own_author_class(self):
        # the classifier is handed the log's OWN claim (author_class) as a
        # HINT via marked_machine, which is exactly the quantity this feature
        # exists to check independently rather than trust — pin that the
        # wiring is what it claims to be.
        seen = {}

        def recording_classify(features, marked_machine=False):
            seen["marked_machine"] = marked_machine
            return "human"

        stub = _make_stub()
        stub.classify_turn = recording_classify
        events = [_ev("r1", AuthorClass.MACHINE, DataType.RESPONSE)]
        store = labelmod.empty_store()
        labelmod.add_authorship_label(store, "r1", "agent", "authorship/1")
        with _WithStub(stub):
            labelmod.score_authorship(events, store)
        self.assertTrue(seen["marked_machine"])


# ── CLI: `label` asks the authorship question when available, skips it
#    gracefully when not ────────────────────────────────────────────────────

class LabelCorpusFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        _write(self.d / "s1.jsonl", [
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line("assistant", "Done. Should I add validation, or keep it minimal?", "2026-02-01T10:05:00Z"),
            _cc_line("user", "it still fails on empty input, fix that", "2026-02-01T10:20:00Z"),
        ])

    def tearDown(self):
        self.tmp.cleanup()


class LabelCliAuthorshipTests(LabelCorpusFixture):
    def test_authorship_question_is_skipped_gracefully_when_the_module_is_absent(self):
        _block_authorship_for_test(self)
        store = self.d / "labels.json"
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                                 "--sample-size", "10", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertIn("not installed", out)
        doc = json.loads(store.read_text())
        self.assertNotIn("authorship_labels", doc)   # unchanged 2-key shape

    def test_authorship_question_is_asked_and_recorded_when_the_module_is_available(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                                 "--sample-size", "10", "--store", str(store)])
        self.assertEqual(rc, 0)
        doc = json.loads(store.read_text())
        self.assertEqual(doc["authorship_version"], "authorship/1")
        self.assertTrue(doc["authorship_labels"])
        for rec in doc["authorship_labels"]:
            self.assertEqual(set(rec.keys()), {"source_ref", "label"})
            self.assertIn(rec["label"], ("human", "agent"))
        # "y" on the authorship question means HUMAN was recorded
        self.assertTrue(all(r["label"] == "human" for r in doc["authorship_labels"]))
        # never leaks content — `_leaks_in` is test_label's scan, planted there
        raw = store.read_text()
        self.assertEqual(_leaks_in(raw, ("build the parser", "config file", "2026-02-01")), [])

    def test_answering_n_on_the_authorship_question_records_agent(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "n"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        doc = json.loads(store.read_text())
        self.assertTrue(all(r["label"] == "agent" for r in doc["authorship_labels"]))

    def test_rerunning_resumes_authorship_labels_too(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        before = json.loads(store.read_text())["authorship_labels"]
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            rc, out, _ = _run(["label", str(self.d), "--adapter", "claude-code",
                              "--sample-size", "10", "--store", str(store)])
        self.assertIn("nothing new to label", out)
        after = json.loads(store.read_text())["authorship_labels"]
        self.assertEqual(before, after)

    def test_a_store_labelled_before_authorship_existed_only_gets_asked_authorship_on_resume(self):
        # first pass: the module is absent, so only the four regex questions
        # get answered (the current, unstubbed state of this repo). Second
        # pass: the module becomes available — resuming must ask ONLY the
        # authorship question per turn, never re-ask an already-answered
        # regex classifier.
        store = self.d / "labels.json"
        _block_authorship_for_test(self)
        answers = itertools.cycle(["y", "n"])
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: next(answers)):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        before = json.loads(store.read_text())["labels"]
        self.assertTrue(before)
        self.assertNotIn("authorship_labels", json.loads(store.read_text()))

        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            rc, out, _ = _run(["label", str(self.d), "--adapter", "claude-code",
                              "--sample-size", "10", "--store", str(store)])
        self.assertEqual(rc, 0)
        doc = json.loads(store.read_text())
        self.assertEqual(doc["labels"], before)   # regex labels untouched, none re-asked
        self.assertTrue(doc["authorship_labels"])  # authorship now filled in

    def test_label_refuses_a_store_graded_under_a_different_authorship_version(self):
        store = self.d / "labels.json"
        store.write_text(json.dumps({"classifier_version": None, "labels": [],
                                     "authorship_version": "authorship/0",
                                     "authorship_labels": []}))
        with _WithStub(_make_stub()):
            rc, out, err = _run(["label", str(self.d), "--adapter", "claude-code",
                                 "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("authorship", err)


# ── CLI: `score` renders the three-valued section ───────────────────────────

class ScoreCliAuthorshipTests(LabelCorpusFixture):
    def test_score_json_includes_a_per_class_authorship_section(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        with _WithStub(_make_stub()):
            rc, out, _ = _run(["score", str(self.d), "--adapter", "claude-code",
                               "--store", str(store), "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertIn("authorship", doc)
        self.assertIn("human", doc["authorship"])
        self.assertIn("agent", doc["authorship"])
        self.assertIn("unknown_pct", doc["authorship"])

    def test_score_markdown_shows_decline_rate_and_never_leaks_the_corpus(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        with _WithStub(_make_stub()):
            rc, out, _ = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 0)
        self.assertIn("## authorship", out)
        self.assertIn("declined (unknown)", out)
        for leak in ("build the parser", "config file", "2026-02-01"):
            self.assertNotIn(leak, out)

    def test_score_refuses_when_authorship_labels_exist_but_module_is_unavailable(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        _block_authorship_for_test(self)
        rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("authorship", err)

    def test_score_refuses_on_a_mismatched_authorship_version(self):
        store = self.d / "labels.json"
        with _WithStub(_make_stub()), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", lambda prompt: "y"):
            _run(["label", str(self.d), "--adapter", "claude-code",
                 "--sample-size", "10", "--store", str(store)])
        doc = json.loads(store.read_text())
        doc["authorship_version"] = "authorship/0"
        store.write_text(json.dumps(doc))
        with _WithStub(_make_stub()):
            rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 2)
        self.assertIn("authorship", err)

    def test_score_with_only_authorship_labels_is_not_treated_as_an_empty_store(self):
        # a store with authorship judgments but no regex-classifier labels
        # must not hit the "no labels yet" refusal meant for a truly empty
        # store.
        store = self.d / "labels.json"
        s = labelmod.empty_store()
        events_dir_store = s
        labelmod.add_authorship_label(events_dir_store, "does-not-matter", "human", "authorship/1")
        store.write_text(json.dumps({
            "classifier_version": None, "labels": [],
            "authorship_version": "authorship/1",
            "authorship_labels": [{"source_ref": "does-not-matter", "label": "human"}],
        }))
        with _WithStub(_make_stub()):
            rc, out, err = _run(["score", str(self.d), "--adapter", "claude-code", "--store", str(store)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
