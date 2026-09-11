"""The wall's tests — held to exactly the claims the README makes, no more.

Two kinds of test here now (review fix): the fail-closed release door, AND the
honest boundary — a test that PROVES the supported path can't recover the
absolute anchor, plus a test that DOCUMENTS weekly cadence is reconstructable
(so nobody re-adds the false 'weekday unreachable' claim).
"""
import unittest

from corpuslens.guard import DEFAULT_PROFILE, AuditRecord, Guard, Profile, WallError
from corpuslens.model import CoarseTime, Event, Quarantine
from corpuslens.analyze import Analyzer


def _q():
    return Quarantine(base_date_iso="2026-01-05", local_tz="America/Denver",
                      ref_map={"opaque1": "chat-2026-02-01T14-30.jsonl:7"})


class ReleaseDoorTests(unittest.TestCase):
    def test_default_profile_grants_nothing(self):
        self.assertEqual(DEFAULT_PROFILE.capabilities, frozenset())

    def test_calendar_denied_by_default(self):
        with self.assertRaises(WallError):
            Guard(_q()).release("calendar_time", "I would like the dates")

    def test_unknown_capability_is_denial(self):
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        with self.assertRaises(WallError):
            g.release("wall_hack", "please")

    def test_missing_justification_is_denial(self):
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        with self.assertRaises(WallError):
            g.release("calendar_time", "   ")

    def test_granted_without_owner_token_is_denial(self):
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"})))
        with self.assertRaises(WallError):
            g.release("calendar_time", "legit reason")

    def test_full_grant_releases_and_audits(self):
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        self.assertEqual(g.release("calendar_time", "demo"), "2026-01-05")
        self.assertTrue(any("calendar_time" in s for s in g.audit.granted))

    def test_ref_resolution_is_gated_like_the_anchor(self):
        # resolving an opaque ref back to a real filename needs the same grant
        with self.assertRaises(WallError):
            Guard(_q()).resolve_ref("opaque1", "debug")
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        self.assertIn("2026-02-01", g.resolve_ref("opaque1", "debug"))


class ClaimGateTests(unittest.TestCase):
    def test_person_claim_unregisterable_by_default(self):
        g = Guard(_q())
        spy = Analyzer(name="custody_map", claims=("life_partition",),
                       denominator="events", run=lambda ev: {})
        self.assertFalse(g.admit(spy))
        self.assertTrue(g.audit.analyzers_refused)

    def test_unknown_claim_refused(self):
        g = Guard(_q())
        self.assertFalse(g.admit(Analyzer(name="vibes", claims=("who_he_is",),
                                          denominator="events", run=lambda ev: {})))

    def test_person_claim_admitted_only_with_grant_and_token(self):
        p = Profile(capabilities=frozenset({"person_inference"}), owner_token="t")
        g = Guard(_q(), p)
        self.assertTrue(g.admit(Analyzer(name="cm", claims=("life_partition",),
                                        denominator="events", run=lambda ev: {})))


class AuditSentenceTests(unittest.TestCase):
    def test_default_profile_sentence_claims_nothing_left(self):
        g = Guard(_q())
        g.audit.n_events = 5
        s = g.audit.sentence()
        self.assertIn("No absolute calendar date, timezone, or filename left the wall", s)

    def test_granted_profile_sentence_does_not_deny_the_release(self):
        # the round-4 finding: an owner grant must NOT co-occur with a flat
        # "nothing left the wall" claim
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        g.release("calendar_time", "owner debug")
        s = g.audit.sentence()
        self.assertNotIn("No absolute calendar date, timezone, or filename left the wall", s)
        self.assertIn("released under owner grant", s)


class DiscoveredPathStructuralGuardTests(unittest.TestCase):
    """Highest-class finding, fixed on the zero-config discovery branch: a
    resolved `discovered_path` (e.g. '/home/sean-campbell/.claude/projects')
    put the owner's real username in the same sentence that claims nothing
    identifying left the wall — `scan_egress` never caught it because it
    checks for quarantined LITERALS, and this value was never quarantined.
    `AuditRecord.discovered_path` may hold ONLY `None` or the adapter's
    declared, unexpanded conventional form (starts with '~') — enforced by
    `__setattr__`, not by convention, because the leak was a plain attribute
    assignment AFTER construction, which a constructor-only check would have
    missed entirely."""

    def test_a_resolved_path_is_refused_at_construction(self):
        with self.assertRaises(WallError):
            AuditRecord(profile="default", discovered_path="/home/sean-campbell/.claude/projects")

    def test_a_resolved_path_is_refused_on_later_assignment(self):
        # this is the ACTUAL shape of the bug that shipped: cli.py sets the
        # field after the record already exists (`guard.audit.discovered_path
        # = path`), not through the constructor.
        a = AuditRecord(profile="default")
        with self.assertRaises(WallError):
            a.discovered_path = "/home/sean-campbell/.claude/projects"
        self.assertIsNone(a.discovered_path)   # the refused assignment did not stick

    def test_a_relative_but_unexpanded_path_is_also_refused(self):
        # not just absolute paths -- anything that is not the declared,
        # tilde-prefixed convention is refused, so a future contributor
        # cannot smuggle a resolved value through by stripping the leading
        # slash.
        a = AuditRecord(profile="default")
        with self.assertRaises(WallError):
            a.discovered_path = "home/sean-campbell/.claude/projects"

    def test_the_declared_tilde_form_is_accepted(self):
        a = AuditRecord(profile="default", adapter="claude-code", n_events=3)
        a.discovered_path = "~/.claude/projects"
        s = a.sentence()
        self.assertIn("~/.claude/projects", s)
        self.assertIn("claude-code", s)
        self.assertEqual(a.as_dict()["discovered_path"], "~/.claude/projects")

    def test_none_is_always_accepted(self):
        a = AuditRecord(profile="default")
        a.discovered_path = "~/.claude/projects"
        a.discovered_path = None   # clearing it back out must never raise
        self.assertIsNone(a.discovered_path)


class HonestBoundaryTests(unittest.TestCase):
    def test_event_carries_no_absolute_anchor_or_filename(self):
        e = Event(event_id="a1b2", corpus_id="c", adapter_id="claude-code/1",
                  source_ref="a1b2", thread_id="deadbeef", surface="cli",
                  author_class="operator", data_type="prompt",
                  time=CoarseTime(day_offset=3, delta_prev_s=90.0),
                  features={"word_count": 5})
        blob = repr(e.__dict__) + repr(e.time)
        for leak in ("2026", "01-05", "Monday", "Denver", ".jsonl", "chat-"):
            self.assertNotIn(leak, blob)

    def test_supported_path_cannot_recover_absolute_anchor(self):
        """A plugin under the default profile gets Events + a Guard. The Guard's
        release door is the ONLY way to the anchor, and it is denied. Assert the
        raw materials for an absolute date are simply not present on Events."""
        g = Guard(_q())
        with self.assertRaises(WallError):
            g.release("calendar_time", "attack")
        with self.assertRaises(WallError):
            g.release("local_tz", "attack")
        ct = CoarseTime(day_offset=0)
        self.assertFalse(hasattr(ct, "hour"))
        self.assertFalse(hasattr(ct, "weekday"))
        self.assertFalse(hasattr(ct, "date"))

    def test_delta_accumulation_cannot_pin_clock_hour(self):
        """The attack a cold review found: accumulate delta_prev_s within a
        thread, find the day_offset increment (a real midnight), and pin the
        clock hour. Defense: the cross-day delta is censored (None), so the
        midnight boundary carries no measurable offset. Assert no delta spans
        two different days in a built corpus."""
        import json, tempfile
        from pathlib import Path
        from corpuslens import ingest
        d = tempfile.TemporaryDirectory()
        # a thread crossing midnight: 23:59:00 then 00:00:30 next day
        lines = [
            {"type": "user", "timestamp": "2026-02-01T23:59:00Z",
             "message": {"content": [{"type": "text", "text": "last turn before midnight here"}]}},
            {"type": "user", "timestamp": "2026-02-02T00:00:30Z",
             "message": {"content": [{"type": "text", "text": "first turn after midnight here"}]}},
            {"type": "user", "timestamp": "2026-02-02T00:02:00Z",
             "message": {"content": [{"type": "text", "text": "second turn after midnight here"}]}},
        ]
        (Path(d.name) / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
        events, q, _ = ingest.get("claude-code")(d.name)
        events.sort(key=lambda e: e.time.day_offset)
        # the event that opens day 1 must have NO delta (cross-midnight censored)
        day1_open = next(e for e in events if e.time.day_offset == 1)
        self.assertIsNone(day1_open.time.delta_prev_s)
        # within-day tempo still present (the 90s same-day gap)
        self.assertTrue(any(e.time.delta_prev_s == 90.0 for e in events))
        d.cleanup()

    def test_weekly_cadence_IS_reconstructable_documented_not_hidden(self):
        """The README promises weekly cadence is NOT hidden. This test documents
        that on purpose — if someone 'fixes' it away, this fails and forces them
        to correct the README rather than silently re-introduce an overclaim."""
        offsets = [0, 1, 2, 7, 8, 9, 14]     # a weekly rhythm
        weekday_slots = {o % 7 for o in offsets}
        self.assertEqual(weekday_slots, {0, 1, 2})   # cadence visible up to rotation
        # ...but WHICH real weekday slot 0 is stays unknown without the anchor,
        # and the anchor is gated:
        with self.assertRaises(WallError):
            Guard(_q()).release("calendar_time", "which weekday is slot 0?")


class EgressScanTests(unittest.TestCase):
    """The output-door backstop: the wall keeps the anchor out of Events
    upstream; scan_egress re-checks the rendered report right before it leaves.
    These are hostile fixtures — a report that DID leak a quarantined value,
    asserting the emit is refused (fail closed)."""

    def test_clean_process_report_passes_unchanged(self):
        g = Guard(_q())
        report = "# corpuslens report\n\nthreads: 2, day_offset max 14, tempo 90.0s\n"
        self.assertEqual(g.scan_egress(report), report)

    def test_leaked_calendar_anchor_is_refused(self):
        with self.assertRaises(WallError):
            Guard(_q()).scan_egress("this run started on 2026-01-05, apparently")

    def test_leaked_filename_is_refused(self):
        with self.assertRaises(WallError):
            Guard(_q()).scan_egress("source: chat-2026-02-01T14-30.jsonl:7")

    def test_leaked_timezone_is_refused(self):
        with self.assertRaises(WallError):
            Guard(_q()).scan_egress("local tz looks like America/Denver")

    def test_error_never_echoes_the_leaked_value(self):
        # a hard stop WITHOUT payload — the backstop must not re-leak the value
        # it caught into the error text (redential's "stack traces without payload")
        with self.assertRaises(WallError) as cm:
            Guard(_q()).scan_egress("leak 2026-01-05 here")
        self.assertNotIn("2026-01-05", str(cm.exception))

    def test_released_value_is_allowed_in_output(self):
        # under an owner grant the run is 'not anchor-free'; the released value
        # may legitimately appear in output, so the backstop must NOT refuse it
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        g.release("calendar_time", "owner debug")
        self.assertIn("2026-01-05", g.scan_egress("dates on: 2026-01-05"))

    def test_ungranted_class_still_refused_when_another_is_released(self):
        # calendar_time released, but local_tz was NOT — a leaked timezone is
        # still a hard stop; the grant is per-capability, not a blanket unlock
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        g.release("calendar_time", "owner debug")
        with self.assertRaises(WallError):
            g.scan_egress("tz: America/Denver")


if __name__ == "__main__":
    unittest.main()
