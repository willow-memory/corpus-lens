"""Share mode: the coarsened report meant to leave the machine.

The rule under test: a field survives coarsening only if it is explicitly
recognised (RATE_FIELDS, `denominator`, `n` -> a band, `error`). Everything
else — known today or invented by a future analyzer — is excluded by
DEFAULT. The `AnalyzerAgnosticTests` class is the one that must keep passing
without edits when a new analyzer is added: it derives what to check FROM the
full report rather than hard-coding today's field names, so it also stands in
for "a new analyzer must not leak a shape by default."
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from corpuslens.analyze import all_analyzers
from corpuslens.cli import main as cli_main
from corpuslens.render import SHARE_CAVEAT, markdown
from corpuslens.share import RATE_FIELDS, band_n, coarsen, coarsen_result

from test_pipeline import _cc_line, _write

# Fields the renderer already treats as presentation text, or as the sentinel
# "denominator"/"n"/"error" fields every result may carry. Never rate data
# themselves, so they are not part of what coarsen() is being asked to strip.
_PRESENTATION_OR_SENTINEL = {"headline", "reading", "vs_coding_population",
                             "denominator", "n", "error"}


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


class BandNTests(unittest.TestCase):
    def test_bands_never_reveal_an_exact_count(self):
        self.assertEqual(band_n(0), "<30")
        self.assertEqual(band_n(29), "<30")
        self.assertEqual(band_n(30), "30-100")
        self.assertEqual(band_n(99), "30-100")
        self.assertEqual(band_n(100), "100-1000")
        self.assertEqual(band_n(999), "100-1000")
        self.assertEqual(band_n(1000), "1000-10000")
        self.assertEqual(band_n(150000), "100000+")

    def test_non_numeric_or_negative_n_is_unknown_not_a_guess(self):
        self.assertEqual(band_n(None), "unknown")
        self.assertEqual(band_n(-1), "unknown")
        self.assertEqual(band_n(True), "unknown")   # bool is not a count


class CoarsenResultTests(unittest.TestCase):
    def test_unknown_fields_are_excluded_by_default(self):
        # A stand-in for "a future analyzer's new field": nothing here is on
        # RATE_FIELDS, so NONE of it should survive — this is the fail-closed
        # behaviour the task exists to prove.
        res = {"headline": "h", "n": 500, "denominator": "turns",
               "brand_new_shape_field": 42, "concurrency_something_pct": 77.7,
               "another_unforeseen_count": 9001}
        out = coarsen_result(res)
        self.assertNotIn("brand_new_shape_field", out)
        self.assertNotIn("concurrency_something_pct", out)   # even a "_pct" name
        self.assertNotIn("another_unforeseen_count", out)
        self.assertEqual(out["n_band"], "100-1000")
        self.assertEqual(out["denominator"], "turns")

    def test_only_allowlisted_rate_fields_survive(self):
        res = {"n": 40, "denominator": "turns", "mid_task_share_pct": 62.0,
               "opener_median_words": 11, "reference": {"x": 1}}
        out = coarsen_result(res)
        self.assertEqual(out["mid_task_share_pct"], 62.0)
        self.assertNotIn("opener_median_words", out)
        self.assertNotIn("reference", out)

    def test_error_result_keeps_the_message_and_denominator_only(self):
        out = coarsen_result({"error": "no operator prompts found", "denominator": "turns"})
        self.assertEqual(out, {"error": "no operator prompts found", "denominator": "turns"})

    def test_no_surviving_rate_gets_an_honest_headline_not_a_false_zero(self):
        # thread_shape-shaped input: nothing on RATE_FIELDS. The synthesized
        # headline must say so plainly rather than reading as "not computable"
        # (that would be FALSE — it was computable, share mode just omits it)
        # or as an empty/zero section (render.py's own rule: a zero is a claim).
        out = coarsen_result({"n": 5, "denominator": "threads", "threads": 5,
                              "concurrency_peak": 3, "resumptions_2to6d": 1})
        self.assertNotIn("threads", out)
        self.assertNotIn("concurrency_peak", out)
        self.assertIn("No share-safe rate", out["headline"])
        self.assertNotIn("not computable", out["headline"])

    def test_bool_values_are_not_mistaken_for_rate_numbers(self):
        out = coarsen_result({"n": 40, "denominator": "d", "mid_task_share_pct": True})
        self.assertNotIn("mid_task_share_pct", out)


class RateFieldsAreReviewedNotGuessedTests(unittest.TestCase):
    def test_shape_shaped_pct_fields_are_deliberately_excluded(self):
        # These exist in the codebase today, end in "_pct", and would pass a
        # naive suffix filter — the allowlist has to be a real review, not a
        # pattern match, and this pins that review down.
        for shape_field in ("single_turn_sessions_pct", "single_day_threads_pct",
                            "burst_pct", "resumed_pct"):
            with self.subTest(field=shape_field):
                self.assertNotIn(shape_field, RATE_FIELDS)


class CorpusFixture(unittest.TestCase):
    """Enough of a corpus to exercise every registered analyzer."""

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


class AnalyzerAgnosticTests(CorpusFixture):
    """These derive the forbidden values FROM the full report rather than
    hard-coding field names, so they keep testing the right thing when an
    analyzer is added — per the task, that is the point of this file."""

    def test_every_non_allowlisted_numeric_field_is_absent_from_share_output(self):
        _, full_out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        _, share_out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                                "--format", "json", "--share"])
        full = json.loads(full_out)["results"]
        share = json.loads(share_out)["results"]
        self.assertTrue(full, "fixture produced no results to check against")
        checked_any = False
        for name, res in full.items():
            self.assertIn(name, share)
            for key, val in res.items():
                if key in RATE_FIELDS or key in _PRESENTATION_OR_SENTINEL:
                    continue
                # Everything else is exactly what share mode must withhold:
                # a shape (count, median, quantile, span, peak, nested ref...)
                # that was not explicitly reviewed onto the allowlist.
                self.assertNotIn(key, share[name],
                                  f"{name}.{key} leaked into share output")
                # A shape value can coincidentally equal a legitimate rate
                # (two independent percentages both landing on 50.0 in a
                # small fixture), so this extra structural check is limited
                # to non-percentage shapes — counts, medians, spans — which
                # are not directly comparable to a "_pct" field's own value
                # and so make a real collision far less likely.
                if (not key.endswith("_pct") and isinstance(val, (int, float))
                        and not isinstance(val, bool) and val not in (0, 1)):
                    checked_any = True
                    self.assertNotIn(
                        val, share[name].values(),
                        f"{name}.{key}'s value {val!r} (a shape, not an allowlisted "
                        f"rate) is still present under some key in the share output")
        self.assertTrue(checked_any, "no numeric shape field found to check — "
                                     "fixture or analyzer set changed underneath this test")

    def test_named_omissions_are_never_keys_in_share_output(self):
        # Belt-and-suspenders on the exact quantities IDEAS.md and the task
        # name outright, in case the generic scan above is ever weakened.
        _, share_out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                                "--format", "json", "--share"])
        share_blob = share_out
        for banned_key in ("median_gap_s", "p25_gap_s", "p75_gap_s", "threads",
                          "concurrency_peak", "concurrency_median",
                          "median_span_days", "max_span_days", "median_active_days",
                          "resumptions_2to6d", "resumptions_7to13d", "resumptions_ge14d",
                          "opener_median_words", "followup_median_words"):
            with self.subTest(key=banned_key):
                self.assertNotIn(f'"{banned_key}"', share_blob)

    def test_no_n_field_carries_an_exact_count_in_share_output(self):
        _, share_out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                                "--format", "json", "--share"])
        doc = json.loads(share_out)
        for name, res in doc["results"].items():
            with self.subTest(analyzer=name):
                self.assertNotIn("n", res)   # only n_band, never the exact n
                if "n_band" in res:
                    self.assertRegex(res["n_band"], r"^(<\d+|\d+-\d+|\d+\+|unknown)$")


class AuditAndEgressTests(CorpusFixture):
    def test_audit_sentence_still_present_in_share_output(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json",
                          "--share"])
        doc = json.loads(out)
        self.assertIn("left the wall", doc["audit"]["sentence"])

    def test_share_output_names_itself_coarsened_never_anonymous(self):
        _, md, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--share"])
        self.assertIn("COARSENED", md)
        low = SHARE_CAVEAT.lower()
        # The words the task forbids are present only as part of an explicit
        # DENIAL ("not anonymized", "not de-identified") — never bare.
        self.assertIn("not anonymized", low)
        self.assertIn("not de-identified", low)
        self.assertIn("not a determination that what remains is safe to publish", low)

    def test_share_json_carries_the_caveat_without_breaking_the_document_shape(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json",
                          "--share"])
        doc = json.loads(out)   # must still parse
        self.assertIn("share_caveat", doc)
        self.assertIn("COARSENED", doc["share_caveat"])
        self.assertEqual(doc["schema_version"], 1)

    def test_unshared_json_has_no_share_caveat(self):
        _, out, _ = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        self.assertNotIn("share_caveat", json.loads(out))

    def test_share_output_still_goes_through_the_egress_backstop(self):
        # Route it through scan_egress exactly as the other renderers are —
        # proven directly by making the RENDERED text (post-coarsening) carry
        # a quarantined value and confirming the CLI still refuses to emit it,
        # the same contract test_cli_surface.py runs for the unshared path.
        from corpuslens import cli
        with mock.patch.object(cli.render, "render", return_value="corpus starts 2026-02-01"):
            rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code", "--share"])
        self.assertEqual(rc, 3)
        self.assertNotIn("2026-02-01", out)
        self.assertNotIn("2026-02-01", err)
        self.assertIn("egress scan", err)

    def test_share_composes_with_json_format_for_machine_use(self):
        # The explicit design ask: --format json --share must work, because a
        # share modifier that only worked with markdown would not serve a
        # machine consumer.
        rc, out, _ = _run(["run", str(self.d), "--adapter", "claude-code",
                           "--format", "json", "--share"])
        self.assertEqual(rc, 0)
        json.loads(out)   # parses cleanly


class CoarsenIsPureTests(CorpusFixture):
    def test_coarsen_does_not_mutate_its_input(self):
        import copy

        from corpuslens import ingest
        events, _, _ = ingest.get("claude-code")(str(self.d))
        results = {a.name: {"denominator": a.denominator, **a.run(events)}
                   for a in all_analyzers()}
        before = copy.deepcopy(results)
        coarsen(results)
        self.assertEqual(results, before)

    def test_markdown_renders_the_coarsened_dict_without_error(self):
        from corpuslens.guard import AuditRecord
        coarsened = coarsen({"a": {"n": 40, "denominator": "turns",
                                   "mid_task_share_pct": 61.9}})
        md = markdown(coarsened, AuditRecord(profile="default"), share=True)
        self.assertIn("mid_task_share_pct", md)
        self.assertIn("30-100", md)   # n_band for n=40
        self.assertIn(SHARE_CAVEAT, md)


if __name__ == "__main__":
    unittest.main()
