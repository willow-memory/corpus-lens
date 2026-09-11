"""SQLite + Postgres adapter tests. The DB adapters must honor the SAME wall the
file adapters do, so these assert the same guarantees: the calendar anchor is
quarantined (never on an Event), unusable rows are counted-not-hidden,
cross-midnight deltas are censored, operator text is injection-stripped, and the
CLI end-to-end emits an anchor-free audit sentence. Postgres tests use the local
`psql` client and skip cleanly if no cluster is reachable."""
import datetime
import io
import re
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens import ingest
from corpuslens.cli import main as cli_main
from corpuslens.guard import Guard
from corpuslens.ingest._rows import classify_role, parse_db_ts, resolve_columns

# A small corpus with: two sessions, an injected wrapper, a cross-midnight gap,
# an unknown role (dropped), a bad timestamp (dropped), and an empty turn (dropped).
ROWS = [
    # (created_at, author, body, session_id)
    ("2026-02-01T10:00:00Z", "user", "build the parser for the config file please", "s1"),
    ("2026-02-01T10:05:00Z", "assistant", "Done. Should I add validation or keep it minimal?", "s1"),
    ("2026-02-02T09:00:00Z", "user", "<system-reminder>x</system-reminder> what does mastery.py return?", "s1"),
    ("2026-02-01T08:00:00Z", "operator", "lets talk about options for the cache layer", "s2"),
    ("2026-02-01T08:01:00Z", "moderator", "this role is unknown and must be dropped", "s2"),
    ("not-a-timestamp",      "user", "bad timestamp row, dropped", "s2"),
    ("2026-02-01T08:02:00Z", "user", "   ", "s2"),
]


def _make_sqlite(path, cols=("created_at", "author", "body", "session_id"), table="turns"):
    con = sqlite3.connect(path)
    con.execute(f'CREATE TABLE "{table}" ({cols[0]} TEXT, {cols[1]} TEXT, '
                f'{cols[2]} TEXT, {cols[3]} TEXT)')
    con.executemany(f'INSERT INTO "{table}" VALUES (?,?,?,?)', ROWS)
    con.commit()
    con.close()


def _pg_ok():
    # Probe a maintenance db explicitly: psql defaults the dbname to the OS user,
    # which often has no matching database. The adapter always receives an
    # explicit dbname, so this only affects the harness's reachability check.
    for maint in ("postgres", "template1"):
        try:
            r = subprocess.run(["psql", maint, "-X", "-tAc", "select 1"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


class RowHelperTests(unittest.TestCase):
    def test_role_classification(self):
        self.assertEqual(classify_role("USER"), "operator")
        self.assertEqual(classify_role("Assistant"), "machine")
        self.assertEqual(classify_role("agent"), "machine")
        self.assertIsNone(classify_role("moderator"))
        self.assertIsNone(classify_role(None))

    def test_ts_parsing_naive_is_utc_and_space_ok(self):
        d1, e1 = parse_db_ts("2026-02-01 10:00:00")      # space separator
        d2, e2 = parse_db_ts("2026-02-01T10:05:00Z")     # 'T' + Z
        self.assertEqual((d1.isoformat(), d2.isoformat()), ("2026-02-01", "2026-02-01"))
        self.assertEqual(e2 - e1, 300.0)                 # 5 min, tz-independent
        self.assertEqual(parse_db_ts("garbage"), (None, None))
        self.assertEqual(parse_db_ts(True), (None, None))  # bool rejected

    def test_ts_hour_only_and_basic_offsets_parse_on_all_pythons(self):
        # Regression for the 3.10 matrix-divergence: `timestamptz::text` on a UTC
        # server emits an hour-only offset ('+00'), which 3.10's fromisoformat
        # rejects. These must yield a real epoch on EVERY interpreter, not fall
        # through to a date-only (epoch None) parse that censors within-day tempo.
        _, e1 = parse_db_ts("2026-02-01 10:00:00+00")    # hour-only offset
        _, e2 = parse_db_ts("2026-02-01 10:05:00+00")
        self.assertIsNotNone(e1)
        self.assertEqual(e2 - e1, 300.0)
        d, e = parse_db_ts("2026-02-01T10:00:00+0530")   # basic (no-colon) offset
        self.assertEqual(d.isoformat(), "2026-02-01")
        self.assertIsNotNone(e)
        # naive == the +00 form, same instant
        _, en = parse_db_ts("2026-02-01 10:00:00")
        self.assertEqual(en, e1)

    def test_ts_date_only_has_no_synthesized_clock(self):
        # A pure date carries no clock — it must NOT fabricate a midnight epoch,
        # which would invent a 0-second tempo delta between two same-day rows.
        self.assertEqual(parse_db_ts("2026-02-01"), (datetime.date(2026, 2, 1), None))

    def test_column_alias_resolution(self):
        m = resolve_columns(["Created_At", "Author", "Body", "Session_Id", "extra"])
        self.assertEqual((m["ts"], m["role"], m["content"], m["session"]),
                         ("Created_At", "Author", "Body", "Session_Id"))


class SqliteAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "corpus.db")
        _make_sqlite(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_wall_quarantine_and_drops(self):
        events, q, dropped = ingest.get("sqlite")(self.db)
        self.assertEqual(q.base_date_iso, "2026-02-01")
        self.assertEqual(dropped.total, 3)                     # unknown role + bad ts + empty
        self.assertEqual(len({e.thread_id for e in events}), 2)
        # injection stripped on the reminder-wrapped operator turn
        stripped = [e for e in events if e.author_class == "operator"
                    and e.features["injected_stripped"]]
        self.assertTrue(stripped and stripped[0].features["code_ref"])

    def test_no_anchor_reaches_events(self):
        events, q, _ = ingest.get("sqlite")(self.db)
        for e in events:
            for fld in (e.event_id, e.source_ref, e.thread_id):
                self.assertFalse(re.search(r"\d{4}-\d\d-\d\d", fld))
                self.assertNotIn(self.db, fld)           # no db path on an Event
        self.assertTrue(q.ref_map)                       # real locators quarantined
        self.assertTrue(all("turns:row" in v for v in q.ref_map.values()))

    def test_cross_midnight_delta_censored(self):
        events, q, _ = ingest.get("sqlite")(self.db)
        # the day-0→day-1 operator turn must have no delta (would pin the hour)
        day1 = [e for e in events if e.time.day_offset == 1]
        self.assertTrue(day1 and all(e.time.delta_prev_s is None for e in day1))
        # within day 0, the 5-min reply delta survives
        self.assertIn(300.0, [e.time.delta_prev_s for e in events
                              if e.time.delta_prev_s is not None])

    def test_table_autodetect_and_explicit(self):
        # add a second table -> autodetect must pick the preferred 'turns'
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE misc (a TEXT)")
        con.commit(); con.close()
        events, _, _ = ingest.get("sqlite")(self.db)           # 'turns' preferred
        self.assertTrue(events)
        events2, _, _ = ingest.get("sqlite")(self.db, table="turns")
        self.assertEqual(len(events), len(events2))

    def test_missing_required_column_errors(self):
        bad = str(Path(self.tmp.name) / "bad.db")
        _make_sqlite(bad, cols=("created_at", "author", "note_wrong", "session_id"))
        with self.assertRaises(ValueError):
            ingest.get("sqlite")(bad)                    # no content column resolvable

    def test_directory_and_missing_rejected(self):
        with self.assertRaises(IsADirectoryError):
            ingest.get("sqlite")(self.tmp.name)
        with self.assertRaises(FileNotFoundError):
            ingest.get("sqlite")(str(Path(self.tmp.name) / "nope.db"))

    def test_cli_end_to_end_sqlite(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(["run", self.db, "--adapter", "sqlite"])
        self.assertEqual(rc, 0)
        report = out.getvalue()
        self.assertIn("No absolute calendar date", report)
        self.assertNotIn("2026-02-01", report)           # anchor never leaks
        self.assertIn("steering_density", report)

    def test_cli_file_adapter_rejects_directory(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main(["run", self.tmp.name, "--adapter", "sqlite"])
        self.assertEqual(rc, 2)
        self.assertIn("single file", err.getvalue())


@unittest.skipUnless(_pg_ok(), "no reachable local Postgres cluster")
class PostgresAdapterTests(unittest.TestCase):
    def setUp(self):
        # Fresh db per test — some tests INSERT, and a shared fixture would leak
        # rows across tests (session-count assertions depend on isolation).
        self.dbname = "corpuslens_test_" + uuid.uuid4().hex[:8]
        subprocess.run(["createdb", self.dbname], check=True,
                       capture_output=True, text=True)
        # created_at is text so the deliberately-bad-timestamp row loads and the
        # ADAPTER (not COPY) is what drops it — the parity we want to test. A real
        # timestamptz column casts to text identically via the adapter's SELECT.
        ddl = ('CREATE TABLE turns (created_at text, author text, '
               'body text, session_id text);')
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c", ddl],
                       check=True, capture_output=True, text=True)
        import csv
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in ROWS:
            w.writerow(r)
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        "COPY turns FROM STDIN WITH (FORMAT csv)"],
                       input=buf.getvalue(), check=True, capture_output=True, text=True)

    def tearDown(self):
        subprocess.run(["dropdb", "--if-exists", self.dbname],
                       capture_output=True, text=True)

    def test_wall_parity_with_sqlite(self):
        events, q, dropped = ingest.get("postgres")(self.dbname)
        self.assertEqual(q.base_date_iso, "2026-02-01")
        self.assertEqual(dropped.total, 3)                     # same three unusable rows
        self.assertEqual(len({e.thread_id for e in events}), 2)
        for e in events:
            self.assertFalse(re.search(r"\d{4}-\d\d-\d\d", e.thread_id))
        day1 = [e for e in events if e.time.day_offset == 1]
        self.assertTrue(day1 and all(e.time.delta_prev_s is None for e in day1))

    def test_embedded_newline_in_body_survives_csv(self):
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        "INSERT INTO turns VALUES "
                        "('2026-02-05T10:00:00Z','user',"
                        "E'line one\\nline two of a longer prompt','s3')"],
                       check=True, capture_output=True, text=True)
        events, _, _ = ingest.get("postgres")(self.dbname)
        self.assertTrue(any(e.time.day_offset == 4 for e in events))  # the s3 turn parsed

    def test_cli_end_to_end_postgres(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(["run", self.dbname, "--adapter", "postgres"])
        self.assertEqual(rc, 0)
        self.assertIn("No absolute calendar date", out.getvalue())
        self.assertNotIn("2026-02-01", out.getvalue())

    def test_real_timestamptz_column_keeps_within_day_tempo(self):
        # Regression for the matrix-divergence finding: a REAL timestamptz column
        # (not the text fixture) renders as an hour-only-offset string via the
        # adapter's ::text cast. Two same-day rows must retain their 5-min delta
        # on every interpreter — on 3.10 the pre-fix parser dropped the epoch and
        # censored this delta while 3.11+ kept it.
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        "CREATE TABLE tt (created_at timestamptz, author text, "
                        "body text, session_id text)"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        "INSERT INTO tt VALUES "
                        "('2026-02-01 10:00:00+00','user','first full-length prompt here','z1'),"
                        "('2026-02-01 10:05:00+00','user','second full-length prompt here','z1')"],
                       check=True, capture_output=True, text=True)
        events, q, _ = ingest.get("postgres")(self.dbname, table="tt")
        deltas = [e.time.delta_prev_s for e in events if e.time.delta_prev_s is not None]
        self.assertIn(300.0, deltas)

    def test_ambiguous_preferred_table_across_schemas_errors(self):
        # F4: a preferred name (e.g. 'turns') in two schemas must not be silently
        # auto-picked — it must ask the user to qualify, like the --table path.
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        "CREATE SCHEMA other; "
                        "CREATE TABLE other.turns (created_at text, author text, "
                        "body text, session_id text)"],
                       check=True, capture_output=True, text=True)
        with self.assertRaises(ValueError):
            ingest.get("postgres")(self.dbname)      # public.turns vs other.turns

    def test_malicious_table_name_cannot_inject(self):
        # The COPY identifier and the information_schema literals must be escaped,
        # not string-interpolated. A table whose NAME tries to break out of its
        # quotes must be read as an ordinary (empty-of-turns) table, never execute
        # the injected statement. If injection worked, 'canary' would be dropped.
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c", "CREATE TABLE canary (x int)"],
                       check=True, capture_output=True, text=True)
        # Short enough to dodge Postgres's 63-byte identifier truncation, so the
        # name round-trips and the adapter really runs it through _columns and the
        # COPY. Unescaped, `")...;DROP...--` would close the FROM identifier and
        # the COPY paren, then execute DROP.
        evil = 'a"); DROP TABLE canary; --'
        dq = evil.replace(chr(34), chr(34) * 2)
        subprocess.run(["psql", self.dbname, "-X", "-q", "-c",
                        f'CREATE TABLE "{dq}" (created_at text, author text, body text)'],
                       check=True, capture_output=True, text=True)
        # adapter may find no usable turns, but must NOT execute the injection.
        try:
            ingest.get("postgres")(self.dbname, table=evil)
        except ValueError:
            pass                                     # a clean adapter-level error is fine
        still = subprocess.run(["psql", self.dbname, "-X", "-tAc",
                                "SELECT to_regclass('public.canary') IS NOT NULL"],
                               capture_output=True, text=True)
        self.assertEqual(still.stdout.strip(), "t")  # canary survived → no injection


if __name__ == "__main__":
    unittest.main()


class ForeignFormatRoleTests(unittest.TestCase):
    """Role vocabularies from other people's corpora, enumerated not guessed.

    Found 2026-09-11 by surveying what public corpora this tool could actually
    be pointed at. Two of the most widely used conversation formats had one
    whole side dropped as unrecognized: OASST pairs `prompter` with
    `assistant`, and the ShareGPT family pairs `human` with `gpt`. Dropping is
    the safe failure and it was counted honestly, but it meant an OASST-shaped
    table reported no operator turns at all.
    """

    def test_oasst_and_sharegpt_roles_resolve(self):
        self.assertEqual(classify_role("prompter"), "operator")   # OASST
        self.assertEqual(classify_role("gpt"), "machine")         # ShareGPT
        self.assertEqual(classify_role("human"), "operator")      # both

    def test_tool_traffic_stays_unrecognized(self):
        """Not an oversight — tool events are not a turn anyone authored.

        They travel beside the roles above in both formats. Mapping them to
        `machine` would inflate `clarification_pull`'s denominator with turns
        nobody spoke, and the claude-code adapter already drops this whole
        class by design.
        """
        for role in ("function_call", "observation", "tool_call", "tool_result"):
            self.assertIsNone(classify_role(role), role)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_oasst_shaped_table_reads_end_to_end(self):
        db = Path(self.tmp.name) / "oasst.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE turns (created_date TEXT, role TEXT, text TEXT, "
                    "message_tree_id TEXT)")
        con.executemany("INSERT INTO turns VALUES (?,?,?,?)", [
            ("2026-02-01T10:00:00Z", "prompter", "how do I phrase this more plainly?", "t1"),
            ("2026-02-01T10:01:00Z", "assistant", "try leading with the verb", "t1"),
            ("2026-02-01T10:04:00Z", "prompter", "that reads much better, thank you", "t1"),
        ])
        con.commit(); con.close()
        events, _, dropped = ingest.get("sqlite")(str(db))
        ops = [e for e in events if e.author_class == "operator"]
        self.assertEqual(len(ops), 2)      # both prompter turns, not zero
        self.assertEqual(dropped.total, 0)
        # created_date and message_tree_id must resolve too: the table uses
        # OASST's own column names throughout, and the thread id failing to
        # resolve is SILENT (session is optional), which would have collapsed
        # every tree in the corpus into one thread with nothing looking wrong.
        self.assertEqual(len({e.thread_id for e in events}), 1)
        self.assertTrue(any(e.time.delta_prev_s for e in events))
