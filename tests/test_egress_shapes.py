"""The structural half of the egress scan.

`tests/test_wall.py::EgressScanTests` covers the LITERAL scan — a report that
leaked a value the Quarantine was holding. These are the complementary case,
and the one the project has actually shipped twice: a value that was **never
quarantined**, so the literal scan is structurally blind to it
(`DiscoveredPathStructuralGuardTests` is the post-mortem of one such bug).

Hostile fixtures throughout: each report below is one a correct run would never
produce, asserting the emit is refused rather than silently allowed.
"""
import unittest

from corpuslens.egress_shapes import STRUCTURAL_SHAPES, find_structural_leaks
from corpuslens.guard import Guard, Profile, WallError
from corpuslens.model import Quarantine


def _q():
    """Deliberately EMPTY quarantine: nothing here is a known literal, so every
    refusal below is the structural scan's own work and not the literal scan's.
    """
    return Quarantine(base_date_iso="", local_tz="", ref_map={})


# A clean, process-only report in the shape the renderers actually emit.
CLEAN = (
    "# corpuslens report\n\n"
    "threads: 2, day_offset max 14, tempo 90.0s, concurrency peak 3\n"
    "mid_task_share: 81.0% (n=42), analyzer_version 1, schema_version 1\n"
    "This run read 21 events (dropped 0, filtered 3) from ~/.claude/projects.\n"
    "No absolute calendar date, timezone, or filename left the wall.\n"
)


class CleanOutputPassesTests(unittest.TestCase):
    def test_a_real_process_report_has_no_structural_leak(self):
        self.assertEqual(find_structural_leaks(CLEAN), [])

    def test_the_declared_tilde_path_is_not_a_home_path_leak(self):
        # the audit record is ALLOWED to name the adapter's declared, unexpanded
        # location; only a RESOLVED one carries the owner's username
        self.assertEqual(find_structural_leaks("read from ~/.claude/projects"), [])

    def test_an_adapter_name_with_a_slash_is_not_a_timezone(self):
        # why the IANA pattern is anchored to real top-level areas rather than a
        # generic Word/Word: this must not fire
        self.assertEqual(find_structural_leaks("adapter: claude-code, source Anthropic/Claude"), [])

    def test_a_tempo_figure_is_not_a_wall_clock_time(self):
        self.assertEqual(find_structural_leaks("tempo median 90.0s, p90 1350.5s"), [])


class StructuralLeakTests(unittest.TestCase):
    def test_resolved_home_path_is_caught(self):
        # THE shipped bug: a resolved discovered_path in the same sentence that
        # claims nothing identifying left the wall
        text = CLEAN.replace("~/.claude/projects", "/home/sean-campbell/.claude/projects")
        self.assertIn("home directory path", find_structural_leaks(text))

    def test_macos_and_windows_home_paths_are_caught(self):
        self.assertIn("home directory path", find_structural_leaks("/Users/sean/logs"))
        self.assertIn("home directory path", find_structural_leaks(r"C:\Users\sean\logs"))

    def test_email_address_is_caught(self):
        self.assertIn("email address", find_structural_leaks("subject: sean@example.com"))

    def test_calendar_date_is_caught(self):
        self.assertIn("calendar date", find_structural_leaks("day 0 was 2026-01-05"))

    def test_weekday_name_is_caught(self):
        self.assertIn("weekday name", find_structural_leaks("peak activity on Sunday"))

    def test_wall_clock_time_is_caught(self):
        self.assertIn("wall-clock time", find_structural_leaks("first event at 03:14"))

    def test_iana_timezone_is_caught(self):
        self.assertIn("IANA timezone", find_structural_leaks("tz America/Denver"))

    def test_labels_only_never_the_matched_text(self):
        # the whole point: this return value goes into an error message, so it
        # must not carry the thing it caught
        leaks = find_structural_leaks("/home/sean-campbell/x and sean@example.com")
        self.assertEqual(sorted(leaks), ["email address", "home directory path"])
        for label in leaks:
            self.assertNotIn("sean", label)


class GrantAwarenessTests(unittest.TestCase):
    """Three shapes are exactly what a released capability legitimately puts in
    the report; two are gated by nothing and refused in every profile."""

    def test_calendar_shapes_allowed_once_calendar_time_is_released(self):
        caps = {"calendar_time"}
        self.assertEqual(find_structural_leaks("2026-01-05, Sunday, 03:14", caps), [])

    def test_timezone_allowed_once_local_tz_is_released(self):
        self.assertEqual(find_structural_leaks("America/Denver", {"local_tz"}), [])

    def test_grants_are_per_capability_not_a_blanket_unlock(self):
        # calendar_time released, local_tz NOT — the timezone is still refused
        self.assertEqual(find_structural_leaks("2026-01-05 America/Denver", {"calendar_time"}),
                         ["IANA timezone"])

    def test_no_capability_ever_permits_a_home_path_or_an_email(self):
        every_cap = {cap for _, cap, _ in STRUCTURAL_SHAPES if cap} | {"person_inference"}
        leaks = find_structural_leaks("/home/sean/x sean@example.com", every_cap)
        self.assertEqual(sorted(leaks), ["email address", "home directory path"])


class GuardIntegrationTests(unittest.TestCase):
    """The gate is only worth anything if it is actually reached from the output
    door every renderer already goes through."""

    def test_scan_egress_passes_a_clean_report_through_unchanged(self):
        self.assertEqual(Guard(_q()).scan_egress(CLEAN), CLEAN)

    def test_scan_egress_refuses_a_never_quarantined_home_path(self):
        # the literal scan CANNOT catch this — the quarantine is empty
        with self.assertRaises(WallError):
            Guard(_q()).scan_egress("read from /home/sean-campbell/.claude/projects")

    def test_the_error_never_echoes_what_it_caught(self):
        # same rule the literal scan is held to: a hard stop without payload,
        # so the gate does not become the leak
        with self.assertRaises(WallError) as cm:
            Guard(_q()).scan_egress("/home/sean-campbell/.claude and sean@example.com")
        msg = str(cm.exception)
        self.assertNotIn("sean", msg)
        self.assertIn("home directory path", msg)
        self.assertIn("email address", msg)

    def test_a_released_capability_reaches_the_structural_scan_too(self):
        g = Guard(_q(), Profile(capabilities=frozenset({"calendar_time"}), owner_token="t"))
        g.release("calendar_time", "owner debug")
        self.assertIn("2026-01-05", g.scan_egress("day 0 was 2026-01-05"))


if __name__ == "__main__":
    unittest.main()
