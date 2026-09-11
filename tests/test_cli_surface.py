"""The added surface: the JSON renderer, the relative-day window, `doctor`,
`adapters`, `analyzers`, and the two new analyzers (tempo, thread_span).

The rule these tests hold: a wider surface must not be a wider wall. Every new
output goes through the same egress backstop, a filtered run must SAY it is a
subset, and the diagnostic command must not become a way to read a corpus's
content or its anchor.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from corpuslens.analyze import Analyzer, all_analyzers
from corpuslens.analyze.tempo import tempo, thread_span
from corpuslens.cli import main as cli_main
from corpuslens.guard import AuditRecord
from corpuslens.model import AuthorClass, CoarseTime, DataType, Event, Surface
from corpuslens.render import json_report, markdown

from test_pipeline import _cc_line, _write   # the same fixtures the spine uses


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


def _ev(thread, day, delta=None, chars=40, author=AuthorClass.OPERATOR,
        dtype=DataType.PROMPT):
    return Event(event_id="e", corpus_id="c", adapter_id="a", source_ref="r",
                 thread_id=thread, surface=Surface.CLI, author_class=author,
                 data_type=dtype, time=CoarseTime(day_offset=day, delta_prev_s=delta),
                 features={"char_count": chars, "word_count": 8})


class CorpusFixture(unittest.TestCase):
    """A small claude-code corpus: 2 threads, days 0..2, base date 2026-02-01."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        _write(self.d / "s1.jsonl", [
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line("assistant", "Done. Should I add validation, or keep it minimal?", "2026-02-01T10:05:00Z"),
            _cc_line("user", "it still fails on empty input, fix that", "2026-02-01T10:20:00Z"),
            _cc_line("user", "lets talk about options for the cache layer", "2026-02-03T09:00:00Z"),
        ])
        _write(self.d / "s2.jsonl", [
            _cc_line("user", "what does mastery.py return on line 40?", "2026-02-02T08:00:00Z"),
            _cc_line("assistant", "It returns the posterior.", "2026-02-02T08:01:00Z"),
        ])

    def tearDown(self):
        self.tmp.cleanup()


class JsonRendererTests(CorpusFixture):
    def test_json_run_is_parseable_and_shaped(self):
        rc, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["audit"]["adapter"], "claude-code")
        self.assertEqual(doc["audit"]["n_events"], doc["audit"]["n_events"])
        self.assertIn("steering_density", doc["results"])
        for res in doc["results"].values():
            self.assertIn("denominator", res)   # every result names what it is out of
            self.assertIsInstance(res["analyzer_version"], int)   # semantics version, not schema
            self.assertTrue(res["grading_question"].strip())      # which GRADING.md question

    def test_json_carries_the_audit_sentence(self):
        # the machine-readable form must not be a way to get numbers WITHOUT the
        # statement of what left the wall
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        doc = json.loads(out)
        self.assertIn("sentence", doc["audit"])
        self.assertIn("left the wall", doc["audit"]["sentence"])
        self.assertIn("caveat", doc)

    def test_json_and_markdown_report_the_same_numbers(self):
        _, j, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        _, m, _ = _run(["run", str(self.d), "--adapter", "claude-code"])
        doc = json.loads(j)
        self.assertIn(doc["audit"]["sentence"], m)
        self.assertIn(str(doc["results"]["steering_density"]["total_turns"]), m)

    def test_json_output_never_carries_the_anchor(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        for leak in ("2026-02-01", "2026", ".jsonl", "s1"):
            self.assertNotIn(leak, out)

    def test_leaking_analyzer_is_stopped_in_json_too(self):
        # the egress backstop guards the OUTPUT DOOR, not one renderer: a new
        # format must not be a way around it.
        leaky = Analyzer(name="leaky", claims=("tempo",), denominator="events",
                         run=lambda ev: {"note": "2026-02-01"})
        with mock.patch("corpuslens.cli.all_analyzers", return_value=[leaky]):
            rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code",
                                 "--format", "json"])
        self.assertEqual(rc, 3)
        self.assertNotIn("2026-02-01", out)
        self.assertNotIn("2026-02-01", err)
        self.assertIn("egress scan", err)

    def test_renderers_agree_on_an_empty_result_set(self):
        audit = AuditRecord(profile="default")
        self.assertIn("corpuslens report", markdown({}, audit))
        self.assertEqual(json.loads(json_report({}, audit))["results"], {})


class WindowTests(CorpusFixture):
    def test_since_day_filters_and_declares_itself(self):
        _, full, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        rc, cut, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                           "--format", "json", "--since-day", "2"])
        self.assertEqual(rc, 0)
        a_full, a_cut = json.loads(full)["audit"], json.loads(cut)["audit"]
        self.assertLess(a_cut["n_events"], a_full["n_events"])
        self.assertEqual(a_cut["n_events"] + a_cut["n_filtered"], a_full["n_events"])
        self.assertTrue(a_cut["filters"])
        # a filtered run must never read as a whole-corpus run
        self.assertIn("subset numbers, not corpus numbers", a_cut["sentence"])

    def test_unfiltered_run_makes_no_subset_claim(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        audit = json.loads(out)["audit"]
        self.assertEqual(audit["filters"], [])
        self.assertEqual(audit["n_filtered"], 0)
        self.assertNotIn("subset numbers", audit["sentence"])

    def test_until_day_is_inclusive(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                          "--format", "json", "--until-day", "0"])
        # day 0 is s1's first three turns (two operator, one assistant)
        self.assertEqual(json.loads(out)["audit"]["n_events"], 3)

    def test_empty_window_is_an_error_not_an_empty_report(self):
        rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code",
                             "--since-day", "99"])
        self.assertEqual(rc, 1)
        self.assertIn("window", err)
        self.assertEqual(out, "")

    def test_inverted_window_is_rejected_before_ingest(self):
        rc, _, err = _run(["run", str(self.d), "--adapter", "claude-code",
                           "--since-day", "5", "--until-day", "2"])
        self.assertEqual(rc, 2)
        self.assertIn("empty", err)

    def test_window_does_not_rebase_day_zero(self):
        # day offsets stay relative to the CORPUS start, not the window start:
        # re-basing would quietly change what "day 0" means between two runs.
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                          "--format", "json", "--since-day", "2"])
        span = json.loads(out)["results"]["thread_span"]
        self.assertEqual(span["threads"], 1)
        self.assertEqual(span["median_span_days"], 1)


class DoctorTests(CorpusFixture):
    def test_doctor_counts_match_the_corpus(self):
        rc, out, _ = _run(["doctor", str(self.d), "--adapter", "claude-code",
                           "--format", "json"])
        self.assertEqual(rc, 0)
        diag = json.loads(out)
        self.assertEqual(diag["events_kept"], 6)
        self.assertEqual(diag["operator_turns"] + diag["machine_turns"], diag["events_kept"])
        self.assertEqual(diag["threads"], 2)
        self.assertEqual(diag["relative_day_span"], 3)
        self.assertEqual(diag["source_file_pattern"], "*.jsonl")
        self.assertTrue(diag["anchor_quarantined"])

    def test_doctor_runs_no_analyzer_and_emits_no_anchor(self):
        _, out, _ = _run(["doctor", str(self.d), "--adapter", "claude-code"])
        for leak in ("2026-02-01", "s1.jsonl", "s2.jsonl", "mastery.py", "cache layer"):
            self.assertNotIn(leak, out)          # no anchor, no filename, no content
        for name in [a.name for a in all_analyzers()]:
            self.assertNotIn(f"# {name}", out)   # no report section ran

    def test_doctor_names_what_this_corpus_cannot_compute(self):
        empty = Path(self.tmp.name) / "nomachine"
        empty.mkdir()
        _write(empty / "s.jsonl", [
            _cc_line("user", "one turn and nothing else at all here", "2026-03-01T10:00:00Z"),
        ])
        _, out, _ = _run(["doctor", str(empty), "--adapter", "claude-code", "--format", "json"])
        notes = " ".join(json.loads(out)["notes"])
        self.assertIn("clarification_pull", notes)
        self.assertIn("tempo", notes)

    def test_doctor_reports_a_bad_adapter_choice_instead_of_crashing(self):
        rc, out, err = _run(["doctor", str(self.d), "--adapter", "cursor", "--format", "json"])
        self.assertEqual(rc, 1)                  # nothing readable — a nonzero verdict
        diag = json.loads(out)
        self.assertEqual(diag["events_kept"], 0)
        self.assertTrue(diag["notes"])
        self.assertEqual(err, "")

    def test_doctor_output_goes_through_the_egress_backstop(self):
        # doctor is an output door like run: were a quarantined value ever to
        # reach a diagnostic line, it must be a hard stop, not a quieter leak.
        from corpuslens import cli
        with mock.patch.object(cli, "_render_doctor",
                               return_value="corpus starts 2026-02-01"):
            rc, out, err = _run(["doctor", str(self.d), "--adapter", "claude-code"])
        self.assertEqual(rc, 3)
        self.assertNotIn("2026-02-01", out)
        self.assertNotIn("2026-02-01", err)
        self.assertIn("egress scan", err)

    def test_doctor_rejects_the_wrong_argument_kind_like_run(self):
        f = self.d / "s1.jsonl"
        rc, _, err = _run(["doctor", str(f), "--adapter", "claude-code"])
        self.assertEqual(rc, 2)
        self.assertIn("directory", err)


class ListingTests(unittest.TestCase):
    def test_adapters_lists_every_registered_adapter_with_its_argument(self):
        rc, out, _ = _run(["adapters", "--format", "json"])
        self.assertEqual(rc, 0)
        rows = {r["adapter"]: r for r in json.loads(out)}
        from corpuslens import ingest
        self.assertEqual(sorted(rows), ingest.available())
        self.assertEqual(rows["sqlite"]["argument"], "file")
        self.assertEqual(rows["postgres"]["argument"], "dsn")
        # a dir adapter names the pattern it actually walks, not an assumed *.jsonl
        self.assertIn("store.db", rows["cursor-store"]["expects"])
        self.assertIn("*.jsonl", rows["claude-code"]["expects"])

    def test_analyzers_lists_claims_and_denominators(self):
        rc, out, _ = _run(["analyzers", "--format", "json"])
        self.assertEqual(rc, 0)
        rows = {r["analyzer"]: r for r in json.loads(out)}
        self.assertEqual(sorted(rows), sorted(a.name for a in all_analyzers()))
        for r in rows.values():
            self.assertTrue(r["denominator"].strip())   # never a bare count
            self.assertTrue(r["claims"])
            self.assertTrue(r["grading_question"].strip())   # every analyzer declares one

    def test_analyzers_markdown_names_which_rubric_question_each_answers(self):
        rc, out, _ = _run(["analyzers"])
        self.assertEqual(rc, 0)
        self.assertIn("GRADING.md: question 1", out)
        self.assertIn("not corpus-measurable", out)   # questions 5-10 named as out of scope

    def test_markdown_listings_are_human_readable(self):
        _, ad, _ = _run(["adapters"])
        _, an, _ = _run(["analyzers"])
        self.assertIn("claude-code", ad)
        self.assertIn("tempo", an)
        self.assertIn("denominator", an.lower())


class TempoAnalyzerTests(unittest.TestCase):
    def test_gaps_are_measured_not_imputed(self):
        events = [_ev("t", 0), _ev("t", 0, 30.0), _ev("t", 0, 90.0), _ev("t", 0, 3600.0)]
        r = tempo(events)
        self.assertEqual(r["n_deltas"], 3)
        self.assertEqual(r["eligible_turns"], 4)
        self.assertEqual(r["delta_coverage_pct"], 75.0)     # the opener has no gap
        self.assertEqual(r["median_gap_s"], 90.0)
        self.assertEqual(r["burst_pct"], round(100 / 3, 1))  # only the 30s gap
        self.assertEqual(r["resumed_pct"], round(100 / 3, 1))  # only the 3600s gap

    def test_a_corpus_without_prompt_clocks_refuses_to_report_tempo(self):
        # cursor-store gives operator turns no delta. The analyzer must say so
        # rather than emit a rate over an empty or invented sample.
        r = tempo([_ev("t", 0), _ev("t", 1), _ev("t", 2)])
        self.assertIn("error", r)
        self.assertEqual(r["delta_coverage_pct"], 0.0)
        self.assertEqual(r["eligible_turns"], 3)
        self.assertNotIn("median_gap_s", r)

    def test_short_and_machine_turns_are_outside_the_denominator(self):
        events = [_ev("t", 0), _ev("t", 0, 10.0, chars=3),
                  _ev("t", 0, 20.0, author=AuthorClass.MACHINE, dtype=DataType.RESPONSE),
                  _ev("t", 0, 40.0)]
        r = tempo(events)
        self.assertEqual(r["eligible_turns"], 2)   # the >=12-char operator prompts only
        self.assertEqual(r["n_deltas"], 1)

    def test_no_operator_prompts_is_an_error_not_a_zero(self):
        r = tempo([_ev("t", 0, author=AuthorClass.MACHINE, dtype=DataType.RESPONSE)])
        self.assertIn("error", r)

    def test_tempo_publishes_no_cumulative_within_day_span(self):
        # the README discloses that a long within-day span loosely bounds the
        # local clock hour. No analyzer may sharpen that disclosed bound.
        r = tempo([_ev("t", 0), _ev("t", 0, 3600.0), _ev("t", 0, 7200.0)])
        for k, v in r.items():
            self.assertNotIn("span", k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                self.assertNotEqual(v, 10800.0)    # the cumulative total, never emitted


class ThreadSpanTests(unittest.TestCase):
    def test_span_is_inclusive_and_density_is_per_thread(self):
        events = [_ev("a", 0), _ev("a", 3),          # span 4 days, 2 active
                  _ev("b", 5)]                       # span 1 day, 1 active
        r = thread_span(events)
        self.assertEqual(r["threads"], 2)
        self.assertEqual(r["max_span_days"], 4)
        self.assertEqual(r["single_day_threads_pct"], 50.0)
        self.assertEqual(r["median_density"], round((0.5 + 1.0) / 2, 3))

    def test_span_carries_no_calendar(self):
        r = thread_span([_ev("a", 0), _ev("a", 400)])
        blob = json.dumps(r)
        self.assertNotIn("2026", blob)
        self.assertEqual(r["median_span_days"], 401)

    def test_empty_corpus_is_an_error_not_a_zero_rate(self):
        self.assertIn("error", thread_span([]))


if __name__ == "__main__":
    unittest.main()
