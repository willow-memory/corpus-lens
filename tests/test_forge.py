"""Forge adapter tests (`corpuslens/ingest/forge.py`).

`tests/fixtures/forge/` is a REAL `~/.forge` written by the Forge's own
documented three-command loop (`forge.entry` twice, then `forge.build_loop`
on its fork fixture) on 2026-09-11 — not a hand-written stand-in. It carries
a real date, a builder name (`rosalind`) and a project name (`rally`), which
is exactly why it is a good fixture: every one of those must be quarantined,
and the tests below check the output for each by the literal value.

The synthetic ledgers exercise the paths the demo does not reach: an ask that
was never answered, a non-turn ledger kind, a malformed line, and two
builders whose names must not be distinguishable from the events.
"""
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens import ingest
from corpuslens.cli import main as cli_main
from corpuslens.ingest import forge
from corpuslens.model import AuthorClass, DataType

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "forge"
REAL_DATE = "2026-09-11"
BUILDER = "rosalind"
PROJECT = "rally"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


def _ask(ts, domain, sha, sealed=False, canonical=None):
    return {"ts": ts, "prev": "x", "kind": "entity_resolve", "domain": domain,
            "surface_sha": sha, "canonical": canonical, "sealed": sealed,
            "confidence": 1.0 if sealed else 0.0}


def _answer(ts, domain, sha, surface, canonical, verifier="someone"):
    return {"ts": ts, "prev": "x", "kind": "entity_seal", "domain": domain,
            "surface": surface, "canonical": canonical, "verifier": verifier,
            "pair_id": "p-" + sha, "surface_sha": sha}


def _write(root: Path, rel: str, records):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) if isinstance(r, dict) else r for r in records) + "\n")


class RealLedgerTests(unittest.TestCase):
    def test_reads_what_the_forge_actually_wrote(self):
        events, q, dropped = ingest.get("forge")(str(FIXTURE))
        # checkpoints/ledger.jsonl: 2 asks (answered), 3 confirms, 2 answers, 2 `seal`
        # projects/rally/…/ledger.jsonl: 2 asks never answered on that ledger
        self.assertEqual(len(events), 7)
        self.assertEqual(dropped.total, 4)
        roles = [e.author_class for e in events]
        self.assertEqual(roles.count(AuthorClass.MACHINE), 5)
        self.assertEqual(roles.count(AuthorClass.OPERATOR), 2)
        self.assertEqual(q.base_date_iso, REAL_DATE)
        self.assertEqual(len({e.thread_id for e in events}), 2, "one thread per decision type")

    def test_the_ask_carries_the_question_it_asked(self):
        events, _, _ = ingest.get("forge")(str(FIXTURE))
        asks = [e for e in events if e.author_class == AuthorClass.MACHINE
                and e.data_type == DataType.RESPONSE and e.features["question"]]
        self.assertGreaterEqual(len(asks), 2, "both real asks were joined to their question")

    def test_names_and_dates_never_reach_an_event(self):
        events, q, _ = ingest.get("forge")(str(FIXTURE))
        blob = json.dumps([{**e.__dict__, "time": e.time.__dict__} for e in events], default=str)
        for literal in (REAL_DATE, BUILDER, PROJECT, "ledger.jsonl"):
            self.assertNotIn(literal, blob, literal)
        # …and the quarantine holds the real locator for every KEPT event. The
        # project ledger's asks were never answered, so nothing from under
        # `projects/rally/` is kept and its path never enters the map either —
        # a dropped record leaves no locator behind.
        self.assertEqual(len(q.ref_map), len(events))
        self.assertTrue(all(re.match(r"checkpoints/ledger\.jsonl:\d+$", ref)
                            for ref in q.ref_map.values()), sorted(q.ref_map.values()))

    def test_run_refuses_the_three_by_name_and_emits_no_anchor(self):
        rc, out, err = _run(["run", str(FIXTURE), "--adapter", "forge", "--format", "json"])
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        refused = " ".join(doc["audit"]["analyzers_refused"])
        for name in forge.UNMEASURABLE:
            self.assertIn(f"{name} (adapter forge:", refused)
            self.assertNotIn(name, doc["results"])
        self.assertIn("refused: steering_density (adapter forge:", doc["audit"]["sentence"])
        self.assertIn("tempo", doc["results"])
        self.assertIn("thread_span", doc["results"])
        for literal in (REAL_DATE, BUILDER, PROJECT):
            self.assertNotIn(literal, out, literal)

    def test_doctor_names_the_unmeasurable_before_a_run(self):
        rc, out, _ = _run(["doctor", str(FIXTURE), "--adapter", "forge", "--format", "json"])
        self.assertEqual(rc, 0)
        diag = json.loads(out)
        self.assertEqual(diag["records_read"], 11)
        self.assertEqual(diag["events_dropped"], 4)
        notes = " ".join(diag["notes"])
        for name in forge.UNMEASURABLE:
            self.assertIn(f"`{name}` is declared unmeasurable by the 'forge' adapter", notes)
        for literal in (REAL_DATE, BUILDER, PROJECT):
            self.assertNotIn(literal, out, literal)


class SyntheticLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unanswered_ask_is_dropped_not_given_a_placeholder(self):
        _write(self.d, "checkpoints/ledger.jsonl", [
            _ask("2026-03-01T10:00:00+00:00", "builder:bob:decision:major", "aaa"),
        ])
        events, _, dropped = ingest.get("forge")(str(self.d))
        self.assertEqual((len(events), dropped.total), (0, 1))

    def test_ask_answer_confirm_become_three_turns_in_one_thread(self):
        dom = "builder:bob:decision:major"
        _write(self.d, "checkpoints/ledger.jsonl", [
            _ask("2026-03-01T10:00:00+00:00", dom, "aaa"),
            {"ts": "2026-03-01T10:00:01+00:00", "prev": "x", "kind": "seal",
             "pair_id": "p-aaa", "verifier": "bob", "source_lang": dom, "target_lang": dom},
            _answer("2026-03-01T10:04:00+00:00", dom, "aaa",
                    "could be web, mobile, desktop — which major?", "web: has a site already",
                    verifier="bob"),
            _ask("2026-03-03T09:00:00+00:00", dom, "aaa", sealed=True, canonical="web: has a site already"),
        ])
        events, q, dropped = ingest.get("forge")(str(self.d))
        self.assertEqual(dropped.total, 1)                       # the `seal` line
        self.assertEqual([e.author_class for e in events],
                         [AuthorClass.MACHINE, AuthorClass.OPERATOR, AuthorClass.MACHINE])
        self.assertEqual(len({e.thread_id for e in events}), 1)
        self.assertEqual([e.time.day_offset for e in events], [0, 0, 2])
        # the answer's delta is the time the maker took: 4 minutes, same day
        self.assertAlmostEqual(events[1].time.delta_prev_s, 240.0)
        self.assertIsNone(events[2].time.delta_prev_s, "a new day carries no delta")
        self.assertTrue(events[0].features["question"])
        self.assertEqual(q.base_date_iso, "2026-03-01")

    def test_non_turn_kinds_and_bad_lines_are_dropped_and_counted(self):
        dom = "builder:bob:decision:major"
        _write(self.d, "checkpoints/ledger.jsonl", [
            "this is not json",
            "[1, 2, 3]",
            {"ts": "2026-03-01T10:00:00+00:00", "kind": "reject_pair", "domain": dom},
            {"ts": "2026-03-01T10:00:00+00:00", "kind": "attach_evidence", "domain": dom},
            _answer("2026-03-01T10:04:00+00:00", dom, "aaa", "which major?", "web"),
            _answer("not a timestamp", dom, "bbb", "which major?", "web"),
            _answer("2026-03-01T10:05:00+00:00", "", "ccc", "which major?", "web"),
        ])
        events, _, dropped = ingest.get("forge")(str(self.d))
        self.assertEqual(len(events), 1)
        self.assertEqual(dropped.total, 6)

    def test_two_builders_are_two_threads_and_neither_name_survives(self):
        for who in ("alice", "bob"):
            dom = f"builder:{who}:decision:major"
            _write(self.d, f"{who}/ledger.jsonl", [
                _answer("2026-03-01T10:04:00+00:00", dom, "aaa", "which major?", "web", verifier=who),
            ])
        events, q, _ = ingest.get("forge")(str(self.d))
        self.assertEqual(len({e.thread_id for e in events}), 2)
        blob = json.dumps([e.__dict__ for e in events], default=str)
        self.assertNotIn("alice", blob)
        self.assertNotIn("bob", blob)
        self.assertTrue(any("alice/ledger.jsonl" in r for r in q.ref_map.values()))

    def test_not_a_directory_is_refused(self):
        f = self.d / "ledger.jsonl"
        f.write_text("{}\n")
        with self.assertRaises(NotADirectoryError):
            ingest.get("forge")(str(f))


class RegistryTests(unittest.TestCase):
    def test_forge_is_registered_as_a_dir_adapter_with_a_home(self):
        self.assertIn("forge", ingest.available())
        self.assertEqual(ingest.source_of("forge"), "dir")
        self.assertEqual(ingest.pattern_of("forge"), "ledger.jsonl")
        self.assertEqual(ingest.default_path_of("forge"), "~/.forge")
        self.assertIn("forge", ingest.discoverable())

    def test_unmeasurable_is_per_adapter_and_defaults_empty(self):
        self.assertEqual(set(ingest.unmeasurable_of("forge")), set(forge.UNMEASURABLE))
        for name in ingest.available():
            if name != "forge":
                self.assertEqual(ingest.unmeasurable_of(name), {}, name)
        self.assertEqual(ingest.unmeasurable_of("no-such-adapter"), {})

    def test_every_declared_name_is_a_real_analyzer(self):
        from corpuslens.analyze import all_analyzers
        names = {a.name for a in all_analyzers()}
        for declared in forge.UNMEASURABLE:
            self.assertIn(declared, names)

    def test_there_is_no_flag_to_run_a_refused_analyzer(self):
        src = (Path(__file__).resolve().parent.parent / "corpuslens" / "cli.py").read_text()
        self.assertNotIn("unmeasurable", src[src.index('sub.add_parser("run"'):src.index('sub.add_parser("doctor"')])


if __name__ == "__main__":
    unittest.main()
