"""Cursor `store.db` adapter tests.

The store is a reverse-engineered format with no published schema, so these
tests build a real SQLite store byte-for-byte the way Cursor writes one —
JSON conversation blobs plus protobuf step blobs encoded here on the wire
format — and assert the adapter's contract against it: the wall holds, every
unusable blob is counted rather than hidden, operator turns carry no invented
clock, and Cursor's injected wrappers never reach a word count.
"""
import io
import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from corpuslens import ingest
from corpuslens.cli import main as cli_main
from corpuslens.ingest.cursor_store import _fields, _step_clocks
from corpuslens.ingest.injection import authored_text
from corpuslens.model import AuthorClass, DataType

START_MS = 1_786_408_136_324          # the thread's own createdAtMs
STEP_MS = 1_786_408_149_842           # a tool step, ~13s later
STEP2_MS = STEP_MS + 4_000


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _len_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _step_blob(*start_times: int) -> bytes:
    """A protobuf blob shaped like Cursor's: field 2 holds step records, each
    carrying a call id (57) and start/end clocks (59/60)."""
    out = b""
    for i, ms in enumerate(start_times):
        step = (_len_field(57, f"call-{i}".encode())
                + _varint_field(59, ms)
                + _varint_field(60, ms + 1000))
        out += _len_field(2, step)
    return out


def _make_store(root: Path, rel: str, blobs, created_ms=START_MS, meta_json=True):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    if meta_json:
        (d / "meta.json").write_text(json.dumps({
            "schemaVersion": 1, "createdAtMs": created_ms,
            "title": "a chat title that must never be emitted",
            "cwd": "/home/someone/secret-project"}))
    con = sqlite3.connect(d / "store.db")
    con.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
    con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    con.executemany("INSERT INTO blobs VALUES (?,?)",
                    [(f"{rel}-{i}", b) for i, b in enumerate(blobs)])
    con.commit()
    con.close()
    return d


def _json_blob(role, content, **extra):
    return json.dumps({"role": role, "content": content, **extra}).encode()


def _corpus(root: Path):
    """Two threads: one ordinary, one exercising every drop path."""
    _make_store(root, "ws/t1", [
        _json_blob("user", "build the parser for the config file please"),
        _step_blob(STEP_MS),
        _json_blob("assistant", "Done. Should I add validation or keep it minimal?"),
        _step_blob(STEP2_MS),
        _json_blob("user", "<git_status>M a.py</git_status>ship it"),
    ])
    _make_store(root, "ws/t2", [
        _json_blob("tool", "a tool result is not a turn"),          # dropped
        _json_blob("system", "nor is a system message"),            # dropped
        _json_blob("user", "   "),                                  # empty -> dropped
        b"{not valid json at all",                                  # dropped
        b"\xff\xfe\xfd opaque or encrypted",                        # dropped
        b"",                                                        # dropped
        _json_blob("user", "lets talk about options for the cache layer"),
    ])


class WireFormat(unittest.TestCase):
    def test_reads_the_shapes_cursor_writes(self):
        msg = _len_field(1, b"hello") + _varint_field(26, START_MS)
        self.assertEqual(list(_fields(msg)),
                         [(1, 2, b"hello"), (26, 0, START_MS)])

    def test_malformed_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            list(_fields(_tag(1, 2) + _varint(99)))       # length overruns
        with self.assertRaises(ValueError):
            list(_fields(_tag(1, 3)))                      # group wiretype

    def test_step_clocks_are_sorted_and_filtered(self):
        self.assertEqual(_step_clocks(_step_blob(STEP2_MS, STEP_MS)),
                         [STEP_MS, STEP2_MS])
        # a varint that is not a plausible ms epoch is not a clock
        self.assertEqual(_step_clocks(_len_field(2, _len_field(57, b"c") +
                                                 _varint_field(59, 42))), [])
        self.assertEqual(_step_clocks(b"\xff\xfe"), [])


class Adapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _corpus(self.root)
        self.events, self.q, self.dropped = ingest.get("cursor-store")(str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_both_threads(self):
        self.assertEqual(len({e.thread_id for e in self.events}), 2)

    def test_prompts_and_responses_are_classified(self):
        prompts = [e for e in self.events if e.data_type is DataType.PROMPT]
        responses = [e for e in self.events if e.data_type is DataType.RESPONSE]
        self.assertEqual(len(prompts), 3)
        self.assertEqual(len(responses), 1)
        self.assertTrue(all(e.author_class is AuthorClass.OPERATOR for e in prompts))

    def test_every_unusable_blob_is_counted_not_hidden(self):
        # t2: tool, system, empty turn, bad json, opaque bytes, empty blob
        self.assertEqual(self.dropped.total, 6)

    def test_operator_turns_carry_no_invented_clock(self):
        """The store does not time prompts. None is the truth; a number would
        be a guess indistinguishable from a measurement downstream."""
        for e in self.events:
            if e.data_type in (DataType.PROMPT, DataType.RESPONSE):
                self.assertIsNone(e.time.delta_prev_s)

    def test_tool_steps_keep_their_real_delta(self):
        deltas = [e.time.delta_prev_s for e in self.events
                  if e.data_type is DataType.TOOL_EVENT]
        self.assertIn((STEP2_MS - STEP_MS) / 1000.0, deltas)

    def test_injected_wrapper_never_reaches_a_word_count(self):
        ship = [e for e in self.events
                if e.data_type is DataType.PROMPT and e.features["injected_stripped"]]
        self.assertEqual(len(ship), 1)
        self.assertEqual(ship[0].features["word_count"], 2)      # "ship it"

    def test_the_wall_holds(self):
        for e in self.events:
            self.assertNotIn("content", e.features)
            self.assertNotIn("/", e.source_ref)                  # opaque, not a path
            self.assertNotIn("secret-project", repr(e))
            self.assertNotIn("chat title", repr(e))
        self.assertIsNotNone(self.q.base_date_iso)               # anchor quarantined
        self.assertTrue(all("store.db" in v for v in self.q.ref_map.values()))

    def test_a_thread_with_no_anchor_invents_none(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _make_store(root, "ws/x", [_json_blob("user", "hello there friend")],
                        meta_json=False)
            events, _, dropped = ingest.get("cursor-store")(str(root))
            self.assertEqual(events, [])
            self.assertGreaterEqual(dropped.total, 1)

    def test_a_file_argument_is_refused(self):
        with self.assertRaises(NotADirectoryError):
            ingest.get("cursor-store")(str(self.root / "ws/t1/store.db"))

    def test_the_store_is_opened_read_only(self):
        db = self.root / "ws/t1/store.db"
        before = db.read_bytes()
        ingest.get("cursor-store")(str(self.root))
        self.assertEqual(db.read_bytes(), before)


class Injection(unittest.TestCase):
    def test_attributed_tags_are_stripped(self):
        raw = '<mcp_instructions description="how to">pages of it</mcp_instructions>\n\nfix the parser'
        self.assertEqual(authored_text(raw), ("fix the parser", True))

    def test_a_compaction_summary_is_not_a_prompt(self):
        for opener in ("[Previous conversation summary]: Summary: ...",
                       "Your conversation was summarized due to length",
                       "This session is being continued from a previous conversation"):
            self.assertEqual(authored_text(opener)[0], "")

    def test_a_human_quoting_one_mid_message_is_untouched(self):
        raw = "why does it say Your conversation was summarized due to length?"
        self.assertEqual(authored_text(raw)[0], raw)

    def test_an_unknown_tag_is_left_alone(self):
        raw = "what do you think about <tag>this</tag>?"
        self.assertEqual(authored_text(raw), (raw, False))


class EndToEnd(unittest.TestCase):
    def test_cli_emits_an_anchor_free_audit_sentence(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _corpus(root)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(["run", str(root), "--adapter", "cursor-store"])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("dropped", out)
            self.assertNotIn("2026-", out)                # no calendar anchor
            self.assertNotIn("store.db", out)             # no filenames
            self.assertIsNone(re.search(r"\bsecret-project\b", out))


if __name__ == "__main__":
    unittest.main()
