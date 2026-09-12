"""Tests for corpuslens.analyze.fingerprint — the leakage-demonstration
computation (IDEAS.md, "The leakage demonstration"; GRADING.md question 9).

Four concerns, matching the module's own contract:
  1. The numbers are computed correctly on known synthetic inputs.
  2. Uniformly random (schedule-free) timestamps must NOT be reported as a
     schedule at any n — the sample-size-bias regression this module was
     revised to fix (2026-09-11 audit: 12 uniform timestamps over 8 weeks
     plug-in-reported 3.974 "bits below uniform" out of a 7.392 maximum).
  3. It NEVER reveals the schedule itself — no weekday, no clock hour, no
     date, no peak-hour identification — including the property test that the
     output is invariant to WHERE on the calendar the same relative pattern
     sits (it cannot leak an absolute phase it never depends on).
  4. It is not wired into the analyzer registry that `corpuslens run` uses
     under the default profile.
"""
import datetime as dt
import math
import random
import unittest

from corpuslens.analyze.fingerprint import (
    HOURS_PER_WEEK,
    NULL_UNRELIABLE_FRACTION,
    timing_fingerprint,
)

DAY_S = 86400.0
HOUR_S = 3600.0
WEEK_S = 7 * DAY_S

# Keys always present. "error" additionally appears only when n/span are too
# small for the hour-of-week estimator to have any signal (see
# RELIABLE_KEYS / UNRELIABLE_KEYS below and BiasCorrectionTests).
BASE_KEYS = {
    "n", "n_days_spanned", "hour_of_week_bins", "hour_of_week_entropy_bits",
    "hour_of_week_max_entropy_bits", "hour_of_week_bits_below_uniform",
    "hour_of_week_null_mean_bits_below_uniform", "hour_of_week_null_trials",
    "hour_of_week_bits_below_uniform_excess",
    "weekly_autocorr_lag7", "weekly_autocorr_rank_pct", "reading",
}
RELIABLE_KEYS = BASE_KEYS
UNRELIABLE_KEYS = BASE_KEYS | {"error"}

# substrings that would indicate the schedule itself leaked out, not just its
# concentration/periodicity — real weekday names, clock-hour phrasing, calendar
# fields. "reading" is guidance prose and is exempt (checked separately below).
FORBIDDEN_SUBSTRINGS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "AM", "PM", "o'clock", "weekday=", "hour=", "peak_hour", "peak_bin",
)


def _package_source_names(module, needle):
    """Whether `module`'s own source text names `needle`. Read with
    `inspect.getsource` rather than by attribute lookup, because importing a
    submodule anywhere in the process binds it onto its package as a side
    effect and proves nothing about what the package itself imports."""
    import inspect
    return needle in inspect.getsource(module)


def _weekly_pattern(n_weeks: int, base: float = 1_700_000_000.0, jitter=None):
    """Synthetic timestamps: one event at the same hour-of-week, `n_weeks`
    weeks running, optionally jittered by a few minutes so it is not a
    degenerate single-second stack."""
    jitter = jitter or [0.0] * n_weeks
    return [base + i * WEEK_S + jitter[i % len(jitter)] for i in range(n_weeks)]


def _spread_pattern(n: int, base: float = 1_700_000_000.0):
    """Synthetic timestamps spread evenly across the week's 168 hour slots,
    one corpus-day apart in a way that visits every slot roughly once — no
    weekly repetition, no hour-of-week concentration."""
    return [base + i * (HOUR_S * 5 + 137) for i in range(n)]  # awkward stride, no clean period


class ConcentrationTests(unittest.TestCase):
    def test_all_same_hour_of_week_slot_is_zero_entropy(self):
        ts = _weekly_pattern(10)
        r = timing_fingerprint(ts)
        self.assertEqual(r["hour_of_week_entropy_bits"], 0.0)
        self.assertAlmostEqual(r["hour_of_week_bits_below_uniform"],
                                r["hour_of_week_max_entropy_bits"], places=3)

    def test_max_entropy_bits_matches_log2_168(self):
        ts = _weekly_pattern(5)
        r = timing_fingerprint(ts)
        self.assertAlmostEqual(r["hour_of_week_max_entropy_bits"], math.log2(HOURS_PER_WEEK), places=3)

    def test_spread_across_many_slots_has_higher_entropy_than_concentrated(self):
        concentrated = timing_fingerprint(_weekly_pattern(20))
        spread = timing_fingerprint(_spread_pattern(60))
        self.assertGreater(spread["hour_of_week_entropy_bits"],
                            concentrated["hour_of_week_entropy_bits"])
        self.assertLess(spread["hour_of_week_bits_below_uniform"],
                         concentrated["hour_of_week_bits_below_uniform"])

    def test_n_reflects_input_count(self):
        ts = _spread_pattern(37)
        self.assertEqual(timing_fingerprint(ts)["n"], 37)


class BiasCorrectionTests(unittest.TestCase):
    """The regression suite for the 2026-09-11 audit finding: the plug-in
    hour-of-week entropy estimator is badly biased upward when n is small
    relative to the 168-bin histogram, so RAW `hour_of_week_bits_below_uniform`
    must never be read as a finding on its own — only
    `hour_of_week_bits_below_uniform_excess` (raw minus a seeded Monte Carlo
    null baseline) may be, and only when it isn't gated off entirely.

    `test_uniformly_random_timestamps_never_report_a_meaningful_schedule` is
    the test that would have caught the audit finding directly: it pins the
    property "no schedule in, no schedule reported" across the n values this
    module claims to support, using ONLY the module's own local
    `random.Random` (never the global `random` module) so this file's own
    randomness never leaks into, or is perturbed by, the function under test.
    """

    # generous on purpose: the property under test is "not a big number", not
    # "exactly this many bits" — the audit's bad reading was 3.974 out of a
    # 7.392 maximum, so anything comfortably under 1 bit is an unambiguous fix.
    NOISE_TOLERANCE_BITS = 1.0

    def test_audit_reproduction_no_longer_reports_a_false_schedule(self):
        """The exact reproduction from the audit: seed=7, 8-week span, n=12.
        Before the fix this reported hour_of_week_bits_below_uniform == 3.974
        as if it were a finding. After the fix the corrected quantity must
        either be near zero or refused outright — never a large number."""
        rng = random.Random(7)
        span = 8 * 7 * 24 * 3600
        ts = [rng.uniform(0, span) for _ in range(12)]
        r = timing_fingerprint(ts)
        excess = r["hour_of_week_bits_below_uniform_excess"]
        if excess is None:
            self.assertIn("error", r)
        else:
            self.assertLess(abs(excess), self.NOISE_TOLERANCE_BITS)
        # the raw, uncorrected number is still exposed for transparency, but
        # it is NOT what a reader is told to read — it must never appear
        # unqualified as "the" schedule reading:
        self.assertIn("hour_of_week_bits_below_uniform", r)
        self.assertIn("excess", r["reading"])

    def test_uniformly_random_timestamps_never_report_a_meaningful_schedule(self):
        """The property test the audit asked for directly: uniformly random
        (schedule-free) timestamps must not report a meaningful schedule at
        ANY supported n. Either the gate refuses (small n) or the excess is
        within noise of zero (n large enough to trust) — never a large
        number presented as if it were a finding."""
        rng = random.Random(20260911)
        span_s = 8 * 7 * DAY_S
        for n in (2, 5, 12, 30, 50, 100, 168, 500, 2000, 6000):
            with self.subTest(n=n):
                ts = [rng.uniform(0, span_s) for _ in range(n)]
                r = timing_fingerprint(ts)
                excess = r["hour_of_week_bits_below_uniform_excess"]
                if excess is None:
                    self.assertIn("error", r,
                                  f"n={n}: excess is None but no error explains why")
                else:
                    self.assertLess(abs(excess), self.NOISE_TOLERANCE_BITS,
                                     f"n={n}: excess {excess} reads as a schedule that isn't there")

    def test_large_n_uniform_random_excess_is_near_zero_not_gated(self):
        """At n=4000 (the audit's second case) there is plenty of signal for
        the estimator: the gate must NOT trigger, and excess must be small."""
        rng = random.Random(7)
        span = 8 * 7 * 24 * 3600
        r = timing_fingerprint([rng.uniform(0, span) for _ in range(4000)])
        self.assertNotIn("error", r)
        self.assertIsNotNone(r["hour_of_week_bits_below_uniform_excess"])
        self.assertLess(abs(r["hour_of_week_bits_below_uniform_excess"]), 0.3)

    def test_small_n_is_refused_rather_than_reported(self):
        """n=12 over an 8-week span (the audit's first case): the corrected
        quantity must be refused outright, not silently reported as ~0 or as
        the raw biased value."""
        rng = random.Random(7)
        span = 8 * 7 * 24 * 3600
        r = timing_fingerprint([rng.uniform(0, span) for _ in range(12)])
        self.assertIn("error", r)
        self.assertIsNone(r["hour_of_week_bits_below_uniform_excess"])
        self.assertIn("n=12", r["error"])

    def test_a_real_weekly_pattern_still_shows_up_once_n_is_large_enough(self):
        """The fix must not blind the tool to a genuine signal: a strongly
        concentrated weekly pattern with enough events to clear the gate
        should report a large positive excess, not get washed out by the
        correction."""
        r = timing_fingerprint(_weekly_pattern(30))
        self.assertNotIn("error", r)
        self.assertIsNotNone(r["hour_of_week_bits_below_uniform_excess"])
        self.assertGreater(r["hour_of_week_bits_below_uniform_excess"], 2.0)

    def test_null_baseline_is_reproducible(self):
        """The Monte Carlo null must be deterministic (fixed internal seed):
        calling twice with the same n/span/data returns the identical
        baseline and the identical overall result."""
        ts = _spread_pattern(40)
        r1 = timing_fingerprint(ts)
        r2 = timing_fingerprint(ts)
        self.assertEqual(r1["hour_of_week_null_mean_bits_below_uniform"],
                          r2["hour_of_week_null_mean_bits_below_uniform"])
        self.assertEqual(r1, r2)

    def test_null_baseline_does_not_perturb_global_random_state(self):
        """The null simulation must use its own private random.Random, never
        the module-global `random` state — otherwise calling this function
        would be an impurity visible to unrelated code that uses `random`."""
        random.seed(12345)
        state_before = random.getstate()
        timing_fingerprint(_weekly_pattern(20))
        self.assertEqual(random.getstate(), state_before)


class PeriodicityTests(unittest.TestCase):
    def test_strong_weekly_repetition_gives_high_positive_autocorr(self):
        ts = _weekly_pattern(12)
        r = timing_fingerprint(ts)
        self.assertIsNotNone(r["weekly_autocorr_lag7"])
        self.assertGreater(r["weekly_autocorr_lag7"], 0.5)

    def test_aperiodic_spread_gives_lower_autocorr_than_weekly_repetition(self):
        periodic = timing_fingerprint(_weekly_pattern(16))
        aperiodic = timing_fingerprint(_spread_pattern(200))
        self.assertIsNotNone(periodic["weekly_autocorr_lag7"])
        if aperiodic["weekly_autocorr_lag7"] is not None:
            self.assertGreater(periodic["weekly_autocorr_lag7"],
                                aperiodic["weekly_autocorr_lag7"])

    def test_too_short_a_span_reports_none_rather_than_a_guess(self):
        # under 8 distinct days -> max_lag < 7 -> cannot estimate lag-7 autocorr
        ts = [1_700_000_000.0 + i * DAY_S for i in range(5)]
        r = timing_fingerprint(ts)
        self.assertIsNone(r["weekly_autocorr_lag7"])
        self.assertIsNone(r["weekly_autocorr_rank_pct"])

    def test_n_days_spanned_is_reported_for_context(self):
        ts = [1_700_000_000.0, 1_700_000_000.0 + 9 * DAY_S]
        self.assertEqual(timing_fingerprint(ts)["n_days_spanned"], 10)


class ContractTests(unittest.TestCase):
    def test_fewer_than_two_timestamps_is_an_error_not_a_guess(self):
        for ts in ([], [1_700_000_000.0]):
            r = timing_fingerprint(ts)
            self.assertIn("error", r)
            self.assertEqual(set(r.keys()), {"n", "error"})

    def test_accepts_datetime_objects_as_well_as_epoch_numbers(self):
        # n=10 is small enough that the bias-correction gate may legitimately
        # refuse the concentration reading (see BiasCorrectionTests) — that is
        # not what this test is checking. This test only checks that datetime
        # input is accepted and produces a well-formed result either way.
        base = dt.datetime(2026, 1, 5, 9, 0, 0)
        ts = [base + dt.timedelta(weeks=i) for i in range(10)]
        r = timing_fingerprint(ts)
        self.assertEqual(r["n"], 10)
        self.assertIn(set(r.keys()), (RELIABLE_KEYS, UNRELIABLE_KEYS))

    def test_mixed_number_and_datetime_input(self):
        # n=3 is far too small for a reliable concentration reading — this
        # test only checks mixed input types don't crash and n is right.
        ts = [1_700_000_000.0, dt.datetime(2026, 1, 5, 9, 0, 0), 1_700_000_000 + 10]
        r = timing_fingerprint(ts)
        self.assertEqual(r["n"], 3)
        self.assertIn(set(r.keys()), (RELIABLE_KEYS, UNRELIABLE_KEYS))

    def test_deterministic(self):
        ts = _weekly_pattern(9)
        self.assertEqual(timing_fingerprint(ts), timing_fingerprint(list(ts)))

    def test_does_not_mutate_input(self):
        ts = _spread_pattern(15)
        before = list(ts)
        timing_fingerprint(ts)
        self.assertEqual(ts, before)

    def test_order_of_input_does_not_matter(self):
        ts = _weekly_pattern(11)
        shuffled = list(reversed(ts))
        self.assertEqual(timing_fingerprint(ts), timing_fingerprint(shuffled))


class NeverRevealsTheScheduleTests(unittest.TestCase):
    """The load-bearing tests for this module: the output is a verdict about
    the FILE, never a description of the person. If a future edit adds a
    field that identifies a real weekday, clock hour, or the peak bin, these
    fail."""

    def test_output_keys_are_exactly_the_declared_set_when_reliable(self):
        # n=30 weekly repeats over a ~29-week span: enough to clear the
        # bias-correction gate (see BiasCorrectionTests), so no "error" key.
        r = timing_fingerprint(_weekly_pattern(30))
        self.assertNotIn("error", r)
        self.assertEqual(set(r.keys()), RELIABLE_KEYS)

    def test_output_keys_are_exactly_the_declared_set_when_refused(self):
        # n=10 over a ~9-week span cannot clear the gate: "error" appears,
        # excess is None, and nothing else is dropped.
        r = timing_fingerprint(_weekly_pattern(10))
        self.assertIn("error", r)
        self.assertIsNone(r["hour_of_week_bits_below_uniform_excess"])
        self.assertEqual(set(r.keys()), UNRELIABLE_KEYS)

    def test_no_forbidden_schedule_language_anywhere_in_the_output(self):
        r = timing_fingerprint(_weekly_pattern(10))
        blob = repr(r)
        for leak in FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(leak, blob)

    def test_output_is_invariant_to_where_on_the_calendar_the_pattern_sits(self):
        """The function cannot leak an absolute phase it does not depend on:
        shifting every timestamp by the same arbitrary real-world offset (a
        different real week, a different real hour of day) must not change a
        single reported number, because every computation here is relative to
        the FIRST timestamp in the input, never to the real calendar."""
        ts = _weekly_pattern(14)
        shifted = [t + 123_456.789 for t in ts]  # not a whole hour, not a whole week
        self.assertEqual(timing_fingerprint(ts), timing_fingerprint(shifted))

    def test_two_different_real_schedules_with_the_same_shape_are_indistinguishable(self):
        """A Tuesday-morning-every-week file and a Saturday-night-every-week
        file with the same relative cadence must produce the identical
        verdict — the point of the whole module is that it describes the
        FILE's shape, not which real hour/day it was."""
        tuesday_morning = dt.datetime(2026, 1, 6, 9, 0, 0)   # a Tuesday
        saturday_night = dt.datetime(2026, 1, 10, 23, 0, 0)  # a Saturday
        a = [tuesday_morning + dt.timedelta(weeks=i) for i in range(12)]
        b = [saturday_night + dt.timedelta(weeks=i) for i in range(12)]
        self.assertEqual(timing_fingerprint(a), timing_fingerprint(b))

    def test_reading_field_states_no_verdict_is_computed(self):
        r = timing_fingerprint(_weekly_pattern(10))
        reading = r["reading"].lower()
        self.assertIn("not a safety threshold", reading)
        for word in ("safe", "unsafe", "identifiable", "not identifiable"):
            # the guidance may use these words only while explicitly disclaiming
            # them ("this is not a X verdict") — it must never assert one as a
            # conclusion. The disclaiming sentence itself is allowed to exist;
            # what must not exist is a bare assertion like "this file is safe."
            self.assertNotIn(f"this file is {word}", reading)
            self.assertNotIn(f"is {word}.", reading)


class NotWiredIntoTheDefaultRegistryTests(unittest.TestCase):
    """`leakage_demonstration` sits on the PROCESS claim allowlist (model.py),
    which means Guard.admit() — correctly, per its own rules — would admit it
    under the DEFAULT profile with no gate at all; only PERSON_CLAIM_TYPES are
    gated. So the only way this computation does not run on every ordinary
    `corpuslens run` is to never hand it to `@register` / import it into
    `analyze/__init__.py`'s registration list. These tests hold that."""

    def test_leakage_demonstration_is_not_in_the_analyzer_registry(self):
        from corpuslens.analyze import all_analyzers
        names = {a.name for a in all_analyzers()}
        claims = {c for a in all_analyzers() for c in a.claims}
        self.assertNotIn("leakage_demonstration", claims)
        self.assertNotIn("fingerprint", names)
        self.assertNotIn("timing_fingerprint", names)

    def test_fingerprint_module_is_not_imported_by_the_analyze_package(self):
        # Importing corpuslens.analyze.fingerprint ANYWHERE in the process
        # (this very test file does, above) binds a `fingerprint` attribute
        # onto the `corpuslens.analyze` package as a side effect of Python's
        # own import machinery — that is true of any submodule and proves
        # nothing about registration. What actually matters is whether
        # analyze/__init__.py itself imports it (which is what would run its
        # `@register` decorator, if it had one, as a side effect of package
        # import) — so check that source directly.
        import corpuslens.analyze as analyze_pkg
        self.assertFalse(_package_source_names(analyze_pkg, "fingerprint"))

    def test_planted_package_source_naming_the_module_is_caught(self):
        # This module's own source names it, several times over; random.py's
        # does not. The scan reads source, not the attribute the import
        # machinery bound.
        import sys
        self.assertTrue(_package_source_names(sys.modules[__name__], "fingerprint"))
        self.assertFalse(_package_source_names(random, "fingerprint"))

    def test_a_default_profile_run_over_ordinary_events_never_computes_it(self):
        """Belt-and-suspenders end-to-end check: build a normal small corpus
        of Events and confirm the default analyzer battery's result set never
        contains this computation's keys — i.e. running `corpuslens run` on a
        completely ordinary corpus cannot surface a leakage-demonstration
        result by accident."""
        from corpuslens.analyze import all_analyzers
        from corpuslens.guard import DEFAULT_PROFILE, Guard
        from corpuslens.model import AuthorClass, CoarseTime, DataType, Event, Quarantine, Surface

        events = [
            Event(event_id=f"e{i}", corpus_id="c", adapter_id="test/1",
                  source_ref=f"e{i}", thread_id="t1", surface=Surface.CLI,
                  author_class=AuthorClass.OPERATOR, data_type=DataType.PROMPT,
                  time=CoarseTime(day_offset=i, delta_prev_s=None),
                  features={"char_count": 20, "word_count": 4})
            for i in range(5)
        ]
        guard = Guard(Quarantine(), DEFAULT_PROFILE)
        results = {}
        for a in all_analyzers():
            if guard.admit(a):
                results[a.name] = a.run(events)
        self.assertNotIn("fingerprint", results)
        self.assertNotIn("timing_fingerprint", results)


if __name__ == "__main__":
    unittest.main()
