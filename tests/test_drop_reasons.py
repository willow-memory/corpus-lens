"""BUGS.md, Open #1 ("doctor's drop warning misfires on agentic corpora"),
now Fixed. Three things pinned here:

  1. `ingest/drops.py::DropCounts` itself — the small stdlib dataclass that
     replaced the old bare `int` third element of an adapter's return tuple.
  2. The `claude-code` adapter classifies every one of its drop sites into
     the closed vocabulary correctly: tool traffic, thinking, an attachment
     and harness bookkeeping are STRUCTURAL (not a turn by design); an
     unparseable line, a missing timestamp, and an empty turn after
     de-injection are MALFORMED (should have been a turn and failed).
  3. `corpuslens doctor`'s warning now keys on the malformed share, not the
     combined total — quiet on a corpus that is almost entirely structural
     drops (the exact 93.7%-dropped-and-nothing-is-wrong case this bug
     report measured), loud on one that is genuinely failing to parse.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens import ingest
from corpuslens.cli import _diagnose, main as cli_main
from corpuslens.ingest.drops import (ATTACHMENT, DropCounts, EMPTY_TURN,
                                     HARNESS_BOOKKEEPING, MISSING_TIMESTAMP,
                                     STRUCTURAL, MALFORMED, SUBAGENT,
                                     THINKING, TOOL_TRAFFIC, UNPARSEABLE_LINE,
                                     reason_class)
from corpuslens.model import DataType, Quarantine

from test_pipeline import _cc_line, _cc_line_with, _write


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


class DropCountsTests(unittest.TestCase):
    def test_add_and_total(self):
        d = DropCounts()
        d.add(TOOL_TRAFFIC, 3)
        d.add(EMPTY_TURN, 2)
        self.assertEqual(d.total, 5)
        self.assertEqual(d.as_dict(), {TOOL_TRAFFIC: 3, EMPTY_TURN: 2})

    def test_structural_and_malformed_split(self):
        d = DropCounts()
        d.add(TOOL_TRAFFIC, 10)
        d.add(THINKING, 5)
        d.add(MISSING_TIMESTAMP, 2)
        d.add(UNPARSEABLE_LINE, 1)
        self.assertEqual(d.structural, 15)
        self.assertEqual(d.malformed, 3)
        self.assertEqual(d.total, 18)

    def test_zero_count_reasons_are_not_recorded(self):
        d = DropCounts()
        d.add(TOOL_TRAFFIC, 0)
        self.assertEqual(d.as_dict(), {})
        self.assertFalse(d)

    def test_merge_combines_two_counts(self):
        a = DropCounts(); a.add(TOOL_TRAFFIC, 2)
        b = DropCounts(); b.add(TOOL_TRAFFIC, 3); b.add(EMPTY_TURN, 1)
        a.merge(b)
        self.assertEqual(a.as_dict(), {TOOL_TRAFFIC: 5, EMPTY_TURN: 1})

    def test_unknown_reason_raises_rather_than_silently_bucketing(self):
        d = DropCounts()
        with self.assertRaises(ValueError):
            d.add("the user's actual prompt text")

    def test_reason_class_is_closed(self):
        self.assertEqual(reason_class(TOOL_TRAFFIC), STRUCTURAL)
        self.assertEqual(reason_class(UNPARSEABLE_LINE), MALFORMED)
        with self.assertRaises(ValueError):
            reason_class("not_a_real_reason")


def _agentic_corpus(d: Path):
    """One real turn, buried under tool/thinking/attachment/bookkeeping
    traffic — the exact SHAPE BUGS.md's Open #1 measured on this project's
    own log: mostly non-turn records, every drop correct."""
    lines = [
        _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
        json.dumps({"type": "assistant", "timestamp": "2026-02-01T10:00:05Z",
                   "message": {"content": [{"type": "tool_use", "id": "t1",
                                           "name": "Bash", "input": {}}]}}),
        json.dumps({"type": "user", "timestamp": "2026-02-01T10:00:06Z",
                   "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                           "content": "ok"}]}}),
        json.dumps({"type": "assistant", "timestamp": "2026-02-01T10:00:07Z",
                   "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}}),
        json.dumps({"type": "attachment", "timestamp": "2026-02-01T10:00:08Z"}),
        json.dumps({"type": "last-prompt", "lastPrompt": "build the parser"}),
        json.dumps({"type": "atis-latch", "atis": True}),
        json.dumps({"type": "assistant", "timestamp": "2026-02-01T10:00:09Z",
                   "message": {"content": [{"type": "text", "text": "Done."}]}}),
    ]
    _write(d / "s1.jsonl", lines)


class ClaudeCodeReasonClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        _agentic_corpus(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tool_and_thinking_and_attachment_and_bookkeeping_are_structural(self):
        events, q, drops = ingest.get("claude-code")(str(self.d))
        by_reason = drops.as_dict()
        self.assertEqual(by_reason.get(TOOL_TRAFFIC), 2)      # tool_use + tool_result
        self.assertEqual(by_reason.get(THINKING), 1)
        self.assertEqual(by_reason.get(ATTACHMENT), 1)
        self.assertEqual(by_reason.get(HARNESS_BOOKKEEPING), 2)  # last-prompt + atis-latch
        self.assertEqual(drops.structural, 6)
        self.assertEqual(drops.malformed, 0)
        self.assertEqual(len(events), 2)   # the one real prompt, and the one real reply

    def test_a_mostly_structural_corpus_reports_zero_malformed(self):
        events, q, drops = ingest.get("claude-code")(str(self.d))
        self.assertGreater(drops.structural, 0)
        self.assertEqual(drops.malformed, 0)

    def test_missing_timestamp_and_unparseable_line_are_malformed(self):
        d2 = Path(tempfile.mkdtemp())
        try:
            _write(d2 / "s1.jsonl", [
                _cc_line("user", "hello", "2026-02-01T10:00:00Z"),
                json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "no ts"}]}}),
                "not even json",
            ])
            events, q, drops = ingest.get("claude-code")(str(d2))
            self.assertEqual(drops.as_dict().get(MISSING_TIMESTAMP), 1)
            self.assertEqual(drops.as_dict().get(UNPARSEABLE_LINE), 1)
            self.assertEqual(drops.malformed, 2)
            self.assertEqual(drops.structural, 0)
        finally:
            import shutil
            shutil.rmtree(d2)

    def test_empty_turn_after_injection_stripping_is_malformed(self):
        d2 = Path(tempfile.mkdtemp())
        try:
            _write(d2 / "s1.jsonl", [
                _cc_line("user", "hello there", "2026-02-01T10:00:00Z"),
                _cc_line("user", "<system-reminder>only harness text</system-reminder>",
                        "2026-02-01T10:00:05Z"),
            ])
            events, q, drops = ingest.get("claude-code")(str(d2))
            self.assertEqual(drops.as_dict(), {EMPTY_TURN: 1})
            self.assertEqual(drops.malformed, 1)
        finally:
            import shutil
            shutil.rmtree(d2)

    def test_subagent_drops_are_structural(self):
        d2 = Path(tempfile.mkdtemp())
        try:
            _write(d2 / "s1.jsonl", [_cc_line("user", "hello", "2026-02-01T10:00:00Z")])
            (d2 / "subagents").mkdir()
            _write(d2 / "subagents" / "agent-1.jsonl",
                  [_cc_line("user", "delegate task", "2026-02-01T10:00:01Z")])
            events, q, drops = ingest.get("claude-code")(str(d2))
            self.assertEqual(drops.as_dict(), {SUBAGENT: 1})
        finally:
            import shutil
            shutil.rmtree(d2)


class DoctorWarningTests(unittest.TestCase):
    """The whole point of the fix: `doctor` stays quiet on a corpus where
    almost everything is dropped but every drop is structural, and warns on
    one where the drops are genuinely malformed."""

    def _diag_for(self, d: Path) -> dict:
        events, quarantine, drops = ingest.get("claude-code")(str(d))
        return _diagnose(events, quarantine, drops, "claude-code", "dir", 1, str(d))

    def test_mostly_structural_drops_do_not_trigger_the_warning(self):
        d = Path(tempfile.mkdtemp())
        try:
            _agentic_corpus(d)
            diag = self._diag_for(d)
            self.assertGreaterEqual(diag["drop_pct"], 50.0)       # still a lot dropped...
            self.assertEqual(diag["malformed_drop_pct"], 0.0)     # ...but none of it malformed
            self.assertFalse(any("should have been a turn" in n
                                 for n in diag["notes"]), diag["notes"])
        finally:
            import shutil
            shutil.rmtree(d)

    def test_mostly_malformed_drops_do_trigger_the_warning(self):
        d = Path(tempfile.mkdtemp())
        try:
            lines = [_cc_line("user", "the one good turn", "2026-02-01T10:00:00Z")]
            # a pile of lines with no usable timestamp: malformed, not structural
            for i in range(5):
                lines.append(json.dumps({
                    "type": "user",
                    "message": {"content": [{"type": "text", "text": f"lost turn {i}"}]}}))
            _write(d / "s1.jsonl", lines)
            diag = self._diag_for(d)
            self.assertGreaterEqual(diag["malformed_drop_pct"], 50.0)
            self.assertTrue(any("should have been a turn" in n
                                for n in diag["notes"]), diag["notes"])
            # the note explicitly excludes the structural bucket from the claim
            self.assertTrue(any("does NOT count" in n for n in diag["notes"]), diag["notes"])
        finally:
            import shutil
            shutil.rmtree(d)

    def test_real_cli_doctor_stays_quiet_on_an_agentic_corpus(self):
        d = Path(tempfile.mkdtemp())
        try:
            _agentic_corpus(d)
            rc, out, _ = _run(["doctor", str(d), "--adapter", "claude-code", "--format", "json"])
            self.assertEqual(rc, 0)
            diag = json.loads(out)
            self.assertNotIn("should have been a turn", " ".join(diag["notes"]))
        finally:
            import shutil
            shutil.rmtree(d)


class HarnessAuthoredUserTurnTests(unittest.TestCase):
    """A user-role record the harness wrote is not the operator typing. Keyed
    on the record's own fields (`isMeta`, `origin.kind`), never on the text —
    the resume prompt reads exactly like something a person would type."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ingest(self, lines):
        _write(self.d / "s1.jsonl", lines)
        return ingest.get("claude-code")(str(self.d))

    def test_a_meta_resume_prompt_is_harness_bookkeeping_not_a_prompt(self):
        events, _, drops = self._ingest([
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line("assistant", "Done.", "2026-02-01T10:05:00Z"),
            _cc_line_with("user", "Continue from where you left off.", "2026-02-01T11:00:00Z",
                          isMeta=True),
        ])
        self.assertEqual(drops.as_dict().get(HARNESS_BOOKKEEPING), 1)
        self.assertEqual(drops.malformed, 0)
        self.assertEqual(sum(1 for e in events if e.data_type is DataType.PROMPT), 1)

    def test_a_task_notification_origin_is_structural_not_an_empty_turn(self):
        # Before: the tag filter stripped the wrapper to nothing and the record
        # was counted as EMPTY_TURN — a *malformed* drop for a correct one.
        events, _, drops = self._ingest([
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line_with("user", "<task-notification><result>done</result></task-notification>",
                          "2026-02-01T10:30:00Z", origin={"kind": "task-notification"}),
        ])
        self.assertEqual(drops.as_dict().get(HARNESS_BOOKKEEPING), 1)
        self.assertIsNone(drops.as_dict().get(EMPTY_TURN))
        self.assertEqual(drops.malformed, 0)
        self.assertEqual(len(events), 1)

    def test_a_human_origin_turn_is_kept(self):
        events, _, drops = self._ingest([
            _cc_line_with("user", "build the parser for the config file please",
                          "2026-02-01T10:00:00Z", origin={"kind": "human"}, promptSource="sdk"),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(drops.total, 0)

    def test_a_record_with_neither_field_is_as_much_a_turn_as_before(self):
        # fail-open on absence: an older harness, or another producer
        events, _, drops = self._ingest([
            _cc_line("user", "Continue from where you left off.", "2026-02-01T10:00:00Z"),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(drops.total, 0)

    def test_the_check_reads_the_field_not_the_text(self):
        # the same resume wording typed by a person (origin says human) stays
        events, _, drops = self._ingest([
            _cc_line_with("user", "Continue from where you left off.", "2026-02-01T10:00:00Z",
                          origin={"kind": "human"}),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(drops.total, 0)


if __name__ == "__main__":
    unittest.main()
