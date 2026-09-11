"""Gemini CLI adapter tests.

There is no real Gemini CLI corpus available to this project — the adapter
(`corpuslens/ingest/gemini_cli.py`) was built from `google-gemini/gemini-cli`'s
own source, not from observed bytes. These fixtures are therefore built to
match what that source WRITES (`chatRecordingService.ts` /
`chatRecordingTypes.ts`), not a guess: a metadata record first, then one JSON
record per turn, `type` in {user, gemini, info, error, warning}, subagent
sessions nested under `<parent-session-id>/<id>.jsonl` with `"kind":"subagent"`
in their own metadata record. See the adapter's module docstring for the exact
files and commit this was read from.
"""
import json
import tempfile
import unittest
from pathlib import Path

from corpuslens import ingest
from corpuslens.model import AuthorClass


def _write(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _meta(session_id, project_hash="proj-hash-1", kind=None, ts="2026-02-01T10:00:00.000Z"):
    r = {"sessionId": session_id, "projectHash": project_hash,
         "startTime": ts, "lastUpdated": ts}
    if kind is not None:
        r["kind"] = kind
    return r


def _msg(mid, ts, mtype, content):
    return {"id": mid, "timestamp": ts, "type": mtype, "content": content}


class GeminiCliAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_session_reads_user_and_model_turns(self):
        _write(self.d / "chats" / "session-2026-02-01T10-00-abcd1234.jsonl", [
            _meta("s1", kind="main"),
            _msg("m1", "2026-02-01T10:00:00.000Z", "user",
                 "build the parser for the config file please"),
            _msg("m2", "2026-02-01T10:05:00.000Z", "gemini",
                 [{"text": "Done. Should I add validation, or keep it minimal?"}]),
            _msg("m3", "2026-02-01T10:20:00.000Z", "user",
                 "it still fails on empty input, fix that"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 3)
        self.assertEqual(dropped, 1)   # only the metadata record
        ops = [e for e in events if e.author_class == AuthorClass.OPERATOR]
        self.assertEqual(len(ops), 2)
        self.assertEqual(q.base_date_iso, "2026-02-01")

    def test_session_context_opener_is_stripped_not_counted_as_a_prompt(self):
        # environmentContext.ts prepends this as the session's first "user"
        # turn on every real session; it must not inflate opener_median_words.
        wrapper = ("<session_context>\nThis is the Gemini CLI. We are setting "
                   "up the context for our chat.\n" + "detail line. " * 200 +
                   "\n</session_context>")
        _write(self.d / "chats" / "session-a.jsonl", [
            _meta("s1", kind="main"),
            _msg("env", "2026-02-01T10:00:00.000Z", "user", [{"text": wrapper}]),
            _msg("m1", "2026-02-01T10:00:05.000Z", "user",
                 "add tests for the parser please"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        ops = [e for e in events if e.author_class == AuthorClass.OPERATOR]
        self.assertEqual(len(ops), 1)
        self.assertLess(ops[0].features["word_count"], 10)
        self.assertEqual(dropped, 2)   # the metadata record + the emptied wrapper turn

    def test_hook_context_is_stripped_but_real_text_survives(self):
        _write(self.d / "chats" / "session-b.jsonl", [
            _meta("s1", kind="main"),
            _msg("m1", "2026-02-01T10:00:00.000Z", "user",
                 [{"text": "apply the fix <hook_context>tool output here, "
                           "a lot of it " * 50 + "</hook_context>"}]),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].features["injected_stripped"])
        self.assertLess(events[0].features["word_count"], 6)

    def test_bookkeeping_records_are_counted_not_treated_as_turns(self):
        _write(self.d / "chats" / "session-c.jsonl", [
            _meta("s1", kind="main"),
            _msg("m1", "2026-02-01T10:00:00.000Z", "user", "a real datable operator turn"),
            {"$set": {"lastUpdated": "2026-02-01T10:00:05.000Z"}},
            {"$rewindTo": "m1"},
            _msg("m2", "2026-02-01T10:00:10.000Z", "info", "Compressed conversation history."),
            _msg("m3", "2026-02-01T10:00:15.000Z", "error", "Tool execution failed."),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 1)
        self.assertEqual(dropped, 5)   # metadata + $set + $rewindTo + info + error

    # ── the subagents/ question, answered for this runtime ──────────────────

    def test_subagent_session_is_not_the_operators_turns(self):
        # main session
        _write(self.d / "chats" / "session-main.jsonl", [
            _meta("parent-session-1", kind="main"),
            _msg("m1", "2026-02-01T10:00:00.000Z", "user",
                 "build the parser for the config file please"),
            _msg("m2", "2026-02-01T10:05:00.000Z", "gemini",
                 "done, it handles empty input now"),
        ])
        # subagent session: nested under a directory named for the PARENT
        # session id, not a fixed literal like Claude Code's "subagents/" —
        # the adapter must key off the "kind" field, not the path.
        _write(self.d / "chats" / "parent-session-1" / "sub-1.jsonl", [
            _meta("sub-1", kind="subagent"),
            _msg("sm1", "2026-02-01T10:06:00.000Z", "user",
                 "Use WebSearch to verify this list of tools. " * 40),
            _msg("sm2", "2026-02-01T10:09:00.000Z", "gemini",
                 "here are the verified results"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        ops = [e for e in events if e.author_class == AuthorClass.OPERATOR]
        self.assertEqual(len(events), 2)              # only the main session
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].features["word_count"], 8)   # not the 200+-word dispatch prompt
        self.assertEqual(dropped, 4)                   # main metadata (1) + all 3 subagent lines
        self.assertEqual(len({e.thread_id for e in events}), 1)

    def test_a_directory_not_named_subagents_still_gets_filtered_by_kind(self):
        # proves the filter is NOT a path/directory-name heuristic: the
        # directory here is named after a session id and would slip past any
        # Claude-Code-style literal "subagents" match.
        _write(self.d / "chats" / "9f2c-random-parent-id" / "child.jsonl", [
            _meta("child-1", kind="subagent"),
            _msg("sm1", "2026-02-01T10:00:00.000Z", "user", "a dispatched task prompt"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(events, [])
        self.assertEqual(dropped, 2)

    def test_missing_metadata_does_not_default_to_subagent(self):
        # a malformed/truncated file with no metadata record at all must not
        # be guessed at either way — it is processed as an ordinary session
        # rather than silently dropped whole, since nothing said "subagent".
        _write(self.d / "chats" / "session-broken.jsonl", [
            _msg("m1", "2026-02-01T10:00:00.000Z", "user", "a real datable operator turn"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 1)

    # ── robustness ────────────────────────────────────────────────────────

    def test_malformed_lines_and_unknown_types_are_counted_not_crashed(self):
        p = self.d / "chats" / "session-d.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text("\n".join([
            "not json at all",
            "42",
            json.dumps(_meta("s1", kind="main")),
            json.dumps({"id": "m1", "timestamp": "not-a-timestamp", "type": "user",
                       "content": "unparseable clock"}),
            json.dumps({"id": "m2", "timestamp": "2026-02-01T10:00:00.000Z",
                       "type": "warning", "content": "some UI warning"}),
            json.dumps(_msg("m3", "2026-02-01T10:00:05.000Z", "user",
                            "a real datable operator turn here")),
        ]) + "\n")
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 1)
        self.assertEqual(dropped, 5)

    def test_unreadable_file_does_not_crash_the_run(self):
        good = self.d / "chats" / "session-e.jsonl"
        _write(good, [_meta("s1", kind="main"),
                      _msg("m1", "2026-02-01T10:00:00.000Z", "user", "a fine operator turn")])
        bogus_dir = self.d / "chats" / "session-f.jsonl"
        bogus_dir.mkdir(parents=True)   # a directory named *.jsonl, not a file
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        self.assertEqual(len(events), 1)

    def test_no_filename_or_session_id_reaches_an_event(self):
        _write(self.d / "chats" / "session-g.jsonl", [
            _meta("very-secret-session-id", kind="main"),
            _msg("m1", "2026-02-01T10:00:00.000Z", "user", "a fine operator turn here"),
        ])
        events, q, dropped = ingest.get("gemini-cli")(str(self.d))
        for e in events:
            for fld in (e.event_id, e.source_ref, e.thread_id):
                self.assertNotIn(".jsonl", fld)
                self.assertNotIn("very-secret-session-id", fld)
        self.assertTrue(any(".jsonl" in v for v in q.ref_map.values()))

    def test_adapter_rejects_file_path_at_library_boundary(self):
        f = self.d / "not-a-dir.jsonl"
        f.write_text("{}\n")
        with self.assertRaises(NotADirectoryError):
            ingest.get("gemini-cli")(str(f))


if __name__ == "__main__":
    unittest.main()
