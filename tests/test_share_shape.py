"""The share-payload shape assertion: `share_shape.find_shape_violations`
and its enforcing caller `Guard.scan_share_shape`.

`tests/test_share.py` covers coarsening itself; `tests/test_egress_shapes.py`
covers the rendered-text structural scan. These are the third, distinct
check `DESIGN-guard-extraction.md` (2a) names as missing: a schema/shape
assertion on the already-coarsened PAYLOAD, before it is ever rendered to
text — "is every field allowlisted, and is every denominator a band" rather
than "does a quarantined value appear in this text."

Hostile fixtures throughout, matching this project's house style: a payload
that forgot to band an `n`, one carrying a stray tempo quantile, one with a
field a future analyzer invented — each must be caught. A correctly
coarsened payload must pass unchanged, with zero violations, so this module
does not become a source of false refusals on honest share output.
"""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens.cli import main as cli_main
from corpuslens.guard import AuditRecord, Guard, Profile, WallError
from corpuslens.model import Quarantine
from corpuslens.share import band_n, coarsen, coarsen_audit
from corpuslens.share_shape import (
    ALLOWED_AUDIT_FIELDS,
    ALLOWED_RESULT_FIELDS,
    find_shape_violations,
)

from test_pipeline import _cc_line, _write


def _quarantine():
    """Empty quarantine: these tests exercise the SHAPE check, never the
    literal scan, so nothing here should be a known quarantined value."""
    return Quarantine(base_date_iso="", local_tz="", ref_map={})


def _clean_payload():
    """A correctly coarsened payload: every result field on the allowlist,
    every denominator a band, the audit record coarsened too. This is the
    baseline every hostile fixture below is a single mutation away from."""
    results = coarsen({
        "steering_density": {"denominator": "operator turns", "n": 42,
                              "mid_task_share_pct": 61.9},
        "composition_mix": {"denominator": "turns", "n": 500,
                            "authored_code_pct": 12.0, "code_ref_pct": 30.0,
                            "delib_pct": 58.0},
        "thread_shape": {"denominator": "threads", "n": 5,
                         "single_day_threads_pct": 40.0},  # a SHAPE field, excluded
    })
    audit = coarsen_audit(AuditRecord(profile="default", n_events=21, n_dropped=7,
                                       adapter="claude-code", n_filtered=0)).as_dict()
    return results, audit


class CleanPayloadPassesTests(unittest.TestCase):
    def test_correctly_coarsened_payload_has_no_violations(self):
        results, audit = _clean_payload()
        self.assertEqual(find_shape_violations(results, audit), [])

    def test_an_analyzer_with_no_surviving_rate_still_passes(self):
        # thread_shape above contributes only its excluded shape field, so its
        # coarsened result is just {denominator, n_band, headline} — no rate
        # survives, and that must not itself be a violation.
        results, audit = _clean_payload()
        self.assertEqual(find_shape_violations({"thread_shape": results["thread_shape"]}, audit), [])

    def test_an_error_result_still_passes(self):
        results, audit = _clean_payload()
        error_result = coarsen({"x": {"error": "no operator prompts found",
                                       "denominator": "turns"}})["x"]
        self.assertEqual(find_shape_violations({"x": error_result}, audit), [])


class ForgotToBandTests(unittest.TestCase):
    """The real, built instance of the gap this module closes: coarsening
    banded every OTHER field but left an exact integer where a band belongs."""

    def test_a_bare_n_that_skipped_banding_is_caught(self):
        results, audit = _clean_payload()
        results["steering_density"]["n"] = 42   # coarsen() would never do this; a bug would
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("'n'" in v for v in violations), violations)

    def test_an_n_band_holding_an_exact_int_is_caught(self):
        results, audit = _clean_payload()
        results["steering_density"]["n_band"] = 42   # band field, wrong TYPE
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("n_band" in v for v in violations), violations)

    def test_exact_audit_n_events_is_caught(self):
        # The precise historical bug: analyzer n's banded, audit n_events not.
        results, audit = _clean_payload()
        audit["n_events"] = 21
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("n_events" in v for v in violations), violations)

    def test_exact_audit_n_dropped_and_n_filtered_are_each_caught(self):
        results, audit = _clean_payload()
        audit["n_dropped"] = 7
        audit["n_filtered"] = 3
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("n_dropped" in v for v in violations), violations)
        self.assertTrue(any("n_filtered" in v for v in violations), violations)

    def test_a_hand_written_string_that_only_looks_like_a_band_is_caught(self):
        # Structure, not just type: a string that is not actually band-shaped
        # must not pass merely because isinstance(value, str) is true.
        results, audit = _clean_payload()
        audit["n_events"] = "twenty-one"
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("n_events" in v for v in violations), violations)


class StrayShapeFieldTests(unittest.TestCase):
    """A tempo quantile (or any other shape statistic) that coarsening failed
    to strip — the class of leak `RATE_FIELDS`'s exclusions exist to prevent."""

    def test_a_stray_tempo_quantile_is_caught(self):
        results, audit = _clean_payload()
        results["tempo"] = {"denominator": "inter-turn gaps", "n_band": "100-1000",
                            "headline": "h", "p50_gap_seconds": 42.0}
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("p50_gap_seconds" in v for v in violations), violations)

    def test_a_shape_pct_field_deliberately_excluded_from_rate_fields_is_caught(self):
        # single_turn_sessions_pct is a SHAPE field, not a rate — RATE_FIELDS
        # excludes it on purpose (see share.py). If it ever reached a share
        # result anyway, this must catch it too, independent of coarsen()'s
        # own filter.
        results, audit = _clean_payload()
        results["steering_density"]["single_turn_sessions_pct"] = 12.0
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("single_turn_sessions_pct" in v for v in violations), violations)


class FutureAnalyzerFieldTests(unittest.TestCase):
    """A field a future analyzer invents, that looks harmless (a plain number,
    an innocuous name) but was never reviewed onto the allowlist."""

    def test_an_unforeseen_field_is_caught_regardless_of_how_harmless_it_looks(self):
        results, audit = _clean_payload()
        results["composition_mix"]["brand_new_confidence_score"] = 0.87
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("brand_new_confidence_score" in v for v in violations), violations)

    def test_an_unforeseen_audit_field_is_caught(self):
        results, audit = _clean_payload()
        audit["internal_debug_note"] = "fine, probably"
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("internal_debug_note" in v for v in violations), violations)

    def test_a_nested_structure_under_an_allowlisted_key_is_caught(self):
        # RATE_FIELDS values are always scalars in a correctly coarsened
        # payload; a nested dict smuggled under an allowlisted key name is
        # not a shape this project reviewed, even though the key itself is.
        results, audit = _clean_payload()
        results["composition_mix"]["authored_code_pct"] = {"value": 12.0, "ci": [10, 14]}
        violations = find_shape_violations(results, audit)
        self.assertTrue(any("authored_code_pct" in v for v in violations), violations)


class ViolationLabelsNeverEchoValuesTests(unittest.TestCase):
    def test_labels_are_strings_naming_fields_not_data(self):
        results, audit = _clean_payload()
        results["steering_density"]["n"] = 42
        audit["n_events"] = 21
        for v in find_shape_violations(results, audit):
            self.assertIsInstance(v, str)


class GuardEnforcementTests(unittest.TestCase):
    """`Guard.scan_share_shape` is the enforcing caller: it raises rather
    than returning a verdict, matching `scan_egress`'s contract."""

    def _guard(self):
        from corpuslens.model import Quarantine
        return Guard(Quarantine(base_date_iso="", local_tz="", ref_map={}), Profile())

    def test_a_clean_payload_does_not_raise(self):
        results, audit = _clean_payload()
        self._guard().scan_share_shape(results, audit)   # must not raise

    def test_a_violation_raises_wallerror(self):
        results, audit = _clean_payload()
        audit["n_events"] = 21
        with self.assertRaises(WallError) as ctx:
            self._guard().scan_share_shape(results, audit)
        self.assertIn("n_events", str(ctx.exception))

    def test_the_error_never_echoes_a_payload_value(self):
        # Same discipline every other Guard error holds to: the exact int
        # itself (21) must never appear in the raised message, only the
        # field name and the fact that it is wrong.
        results, audit = _clean_payload()
        audit["n_events"] = 987654
        with self.assertRaises(WallError) as ctx:
            self._guard().scan_share_shape(results, audit)
        self.assertNotIn("987654", str(ctx.exception))


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


class CliWiringTests(unittest.TestCase):
    """The check must actually run on the real `--share` path, and must not
    reject honest output — a false refusal here would be as serious a bug
    as a missed leak."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name) / "proj"
        self.d.mkdir()
        lines = [_cc_line("user" if i % 2 == 0 else "assistant", f"turn {i}",
                           f"2026-02-{1 + i // 24:02d}T{i % 24:02d}:00:00Z")
                 for i in range(40)]
        _write(self.d / "session.jsonl", lines)

    def tearDown(self):
        self._tmp.cleanup()

    def test_real_share_run_passes_the_shape_scan_and_exits_zero(self):
        rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code",
                             "--format", "json", "--share"])
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        self.assertIn("share_caveat", doc)

    def test_a_forced_unbanded_audit_n_events_is_refused_before_emit(self):
        from corpuslens import cli

        real_coarsen_audit = cli.share_mod.coarsen_audit

        def _broken_coarsen_audit(audit):
            coarsened = real_coarsen_audit(audit)
            import dataclasses
            return dataclasses.replace(coarsened, n_events=audit.n_events)  # "forgot" to band

        from unittest import mock
        with mock.patch.object(cli.share_mod, "coarsen_audit", side_effect=_broken_coarsen_audit):
            rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code",
                                 "--format", "json", "--share"])
        self.assertEqual(rc, 3)
        self.assertEqual(out, "")
        self.assertIn("n_events", err)

    def test_no_analyzer_change_needed_for_unshared_runs(self):
        # The shape scan only runs when --share is passed; an ordinary run
        # must be entirely unaffected.
        rc, out, err = _run(["run", str(self.d), "--adapter", "claude-code", "--format", "json"])
        self.assertEqual(rc, 0, err)


class AllowlistsAreReviewedSetsTests(unittest.TestCase):
    """Pin the allowlists themselves so a silent addition is visible in a
    diff, matching `test_share.py::RateFieldsAreReviewedNotGuessedTests`."""

    def test_result_meta_fields_are_exactly_the_reviewed_set(self):
        self.assertTrue({"denominator", "n_band", "headline", "error"} <= ALLOWED_RESULT_FIELDS)

    def test_audit_fields_are_exactly_the_reviewed_set(self):
        self.assertEqual(ALLOWED_AUDIT_FIELDS, frozenset({
            "profile", "adapter", "discovered_path", "granted", "denied",
            "analyzers_run", "analyzers_refused", "n_events", "n_dropped",
            "filters", "n_filtered", "subject", "subject_reason", "subject_consent",
            "sentence",
        }))


if __name__ == "__main__":
    unittest.main()


class ErrorMessageLegibilityTests(unittest.TestCase):
    """A total coarsening failure violates once per field per analyzer. The
    uncapped message ran past 4,000 characters, which buries the count and the
    instruction under a wall of field names."""

    def test_many_violations_are_summarized_not_all_listed(self):
        # an uncoarsened payload across several analyzers: dozens of violations
        raw = {
            f"analyzer_{i}": {"n": 21, "median_gap_s": 90.0, "reading": "x",
                              "reference": "y", "analyzer_version": 1}
            for i in range(6)
        }
        with self.assertRaises(WallError) as cm:
            Guard(_quarantine()).scan_share_shape(raw, _clean_payload()[1])
        msg = str(cm.exception)
        self.assertLess(len(msg), 1200, "error message is still unreadably long")
        self.assertIn("and ", msg)
        self.assertIn("more", msg)
        # the count is what tells a reader "the step did not run at all"
        self.assertRegex(msg, r"\d+ shape violation\(s\)")

    def test_a_single_violation_is_named_in_full_with_no_summary(self):
        results, audit = _clean_payload()
        audit["n_events"] = 21            # exactly one thing wrong
        with self.assertRaises(WallError) as cm:
            Guard(_quarantine()).scan_share_shape(results, audit)
        msg = str(cm.exception)
        self.assertIn("n_events", msg)
        self.assertNotIn("and 0 more", msg)
        self.assertNotIn(" more —", msg)
