"""Tests for corpuslens.analyze.fingerprint — the leakage-demonstration
computation (IDEAS.md, "The leakage demonstration"; GRADING.md question 9).

Three concerns, matching the module's own contract:
  1. The numbers are computed correctly on known synthetic inputs.
  2. It NEVER reveals the schedule itself — no weekday, no clock hour, no
     date, no peak-hour identification — including the property test that the
     output is invariant to WHERE on the calendar the same relative pattern
     sits (it cannot leak an absolute phase it never depends on).
  3. It is not wired into the analyzer registry that `corpuslens run` uses
     under the default profile.
"""
import datetime as dt
import math
import unittest

from corpuslens.analyze.fingerprint import (
    HOURS_PER_WEEK,
    timing_fingerprint,
)

DAY_S = 86400.0
HOUR_S = 3600.0
WEEK_S = 7 * DAY_S

EXPECTED_KEYS = {
    "n", "n_days_spanned", "hour_of_week_bins", "hour_of_week_entropy_bits",
    "hour_of_week_max_entropy_bits", "hour_of_week_bits_below_uniform",
    "weekly_autocorr_lag7", "weekly_autocorr_rank_pct", "reading",
}

# substrings that would indicate the schedule itself leaked out, not just its
# concentration/periodicity — real weekday names, clock-hour phrasing, calendar
# fields. "reading" is guidance prose and is exempt (checked separately below).
FORBIDDEN_SUBSTRINGS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "AM", "PM", "o'clock", "weekday=", "hour=", "peak_hour", "peak_bin",
)


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
        base = dt.datetime(2026, 1, 5, 9, 0, 0)
        ts = [base + dt.timedelta(weeks=i) for i in range(10)]
        r = timing_fingerprint(ts)
        self.assertNotIn("error", r)
        self.assertEqual(r["n"], 10)

    def test_mixed_number_and_datetime_input(self):
        ts = [1_700_000_000.0, dt.datetime(2026, 1, 5, 9, 0, 0), 1_700_000_000 + 10]
        r = timing_fingerprint(ts)
        self.assertNotIn("error", r)

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

    def test_output_keys_are_exactly_the_declared_set(self):
        r = timing_fingerprint(_weekly_pattern(10))
        self.assertEqual(set(r.keys()), EXPECTED_KEYS)

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
        import inspect
        import corpuslens.analyze as analyze_pkg
        src = inspect.getsource(analyze_pkg)
        self.assertNotIn("fingerprint", src)

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
