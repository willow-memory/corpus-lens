"""`corpuslens diff a.json b.json` — the delta between two runs.

The rule these tests hold: a diff must never present a delta as a change in
the user's process when it could be a change in the software or the corpus
scope. Different adapter / different schema_version => hard refusal, no
numbers at all. A filtered side, or a mismatched analyzer version, => the
diff still runs but says so where it cannot be missed. A file that is not a
corpuslens JSON report is a clear error, never a traceback.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens import diff as diffmod
from corpuslens.cli import main as cli_main

from test_pipeline import _cc_line, _write


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


def _make_corpus(dirpath: Path, extra_turn: bool = False, base_day="2026-02-01"):
    lines = [
        _cc_line("user", "build the parser for the config file please", f"{base_day}T10:00:00Z"),
        _cc_line("assistant", "Done. Should I add validation, or keep it minimal?",
                 f"{base_day}T10:05:00Z"),
        _cc_line("user", "it still fails on empty input, fix that", f"{base_day}T10:20:00Z"),
    ]
    if extra_turn:
        lines.append(_cc_line("user", "also handle unicode please", f"{base_day}T10:40:00Z"))
    _write(dirpath / "s1.jsonl", lines)


class DiffFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "a").mkdir()
        (self.d / "b").mkdir()
        _make_corpus(self.d / "a")
        _make_corpus(self.d / "b", extra_turn=True)
        rc, _, _ = _run(["run", str(self.d / "a"), "--adapter", "claude-code",
                         "--format", "json", "--out", str(self.d / "a.json")])
        self.assertEqual(rc, 0)
        rc, _, _ = _run(["run", str(self.d / "b"), "--adapter", "claude-code",
                         "--format", "json", "--out", str(self.d / "b.json")])
        self.assertEqual(rc, 0)

    def tearDown(self):
        self.tmp.cleanup()


class LoadReportTests(DiffFixture):
    def test_a_real_report_loads(self):
        doc = diffmod.load_report(str(self.d / "a.json"))
        self.assertEqual(doc["schema_version"], 1)

    def test_missing_file_is_a_clear_error_not_a_traceback(self):
        with self.assertRaises(diffmod.DiffError):
            diffmod.load_report(str(self.d / "does-not-exist.json"))

    def test_malformed_json_is_a_clear_error(self):
        bad = self.d / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(diffmod.DiffError) as ctx:
            diffmod.load_report(str(bad))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_json_that_is_not_a_corpuslens_report_is_refused_with_a_clear_message(self):
        not_ours = self.d / "not-ours.json"
        not_ours.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        with self.assertRaises(diffmod.DiffError) as ctx:
            diffmod.load_report(str(not_ours))
        self.assertIn("not a corpuslens JSON report", str(ctx.exception))

    def test_a_json_array_is_refused_not_crashed_on(self):
        arr = self.d / "arr.json"
        arr.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(diffmod.DiffError):
            diffmod.load_report(str(arr))

    def test_cli_reports_a_bad_file_cleanly(self):
        bad = self.d / "bad.json"
        bad.write_text("nope", encoding="utf-8")
        rc, out, err = _run(["diff", str(bad), str(self.d / "b.json")])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)


class ComparableDiffTests(DiffFixture):
    def test_cli_diff_succeeds_and_reports_deltas(self):
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(self.d / "b.json"),
                           "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertFalse(doc["refused"])
        self.assertIn("steering_density", doc["analyzers"])
        entry = doc["analyzers"]["steering_density"]
        self.assertEqual(entry["status"], "compared")
        self.assertIn("total_turns", entry["deltas"])
        self.assertEqual(entry["deltas"]["total_turns"]["a"], 2)
        self.assertEqual(entry["deltas"]["total_turns"]["b"], 3)
        self.assertEqual(entry["deltas"]["total_turns"]["delta"], 1)

    def test_pct_change_from_zero_is_undefined_not_infinite_or_zero(self):
        d = diffmod.compare(
            {"schema_version": 1, "audit": {"sentence": "s", "adapter": "claude-code"},
             "results": {"x": {"analyzer_version": 1, "headline": "h", "n": 1, "v": 0}},
             "caveat": "c"},
            {"schema_version": 1, "audit": {"sentence": "s", "adapter": "claude-code"},
             "results": {"x": {"analyzer_version": 1, "headline": "h", "n": 1, "v": 5}},
             "caveat": "c"})
        self.assertIsNone(d["analyzers"]["x"]["deltas"]["v"]["pct_change"])
        self.assertEqual(d["analyzers"]["x"]["deltas"]["v"]["delta"], 5)

    def test_both_audit_sentences_appear_in_the_output(self):
        doc_a = diffmod.load_report(str(self.d / "a.json"))
        doc_b = diffmod.load_report(str(self.d / "b.json"))
        d = diffmod.compare(doc_a, doc_b)
        md = diffmod.render_markdown(d)
        self.assertIn(doc_a["audit"]["sentence"], md)
        self.assertIn(doc_b["audit"]["sentence"], md)
        parsed = json.loads(diffmod.render_json(d))
        self.assertEqual(parsed["a"]["audit"]["sentence"], doc_a["audit"]["sentence"])
        self.assertEqual(parsed["b"]["audit"]["sentence"], doc_b["audit"]["sentence"])

    def test_caveat_travels_with_the_diff_too(self):
        doc_a = diffmod.load_report(str(self.d / "a.json"))
        doc_b = diffmod.load_report(str(self.d / "b.json"))
        d = diffmod.compare(doc_a, doc_b)
        self.assertIn("caveat", d)
        md = diffmod.render_markdown(d)
        self.assertIn(d["caveat"], md)

    def test_non_numeric_and_metadata_fields_are_not_diffed(self):
        doc_a = diffmod.load_report(str(self.d / "a.json"))
        doc_b = diffmod.load_report(str(self.d / "b.json"))
        d = diffmod.compare(doc_a, doc_b)
        for entry in d["analyzers"].values():
            if entry["status"] != "compared":
                continue
            self.assertNotIn("analyzer_version", entry["deltas"])
            self.assertNotIn("headline", entry["deltas"])
            self.assertNotIn("denominator", entry["deltas"])
            self.assertNotIn("reference", entry["deltas"])

    def test_identical_runs_diff_to_all_zero_deltas(self):
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(self.d / "a.json"),
                           "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        for entry in doc["analyzers"].values():
            if entry["status"] != "compared":
                continue
            for field, v in entry["deltas"].items():
                self.assertEqual(v["delta"], 0, field)


class RefusalTests(DiffFixture):
    def _with_audit_field(self, path, **overrides):
        doc = json.loads(Path(path).read_text())
        doc["audit"].update(overrides)
        out = Path(path).with_name(Path(path).stem + "-mut.json")
        out.write_text(json.dumps(doc))
        return out

    def test_different_adapter_is_a_hard_refusal(self):
        b_other = self._with_audit_field(self.d / "b.json", adapter="cursor")
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(b_other), "--format", "json"])
        self.assertEqual(rc, 1)
        doc = json.loads(out)
        self.assertTrue(doc["refused"])
        self.assertTrue(any("adapter differs" in r for r in doc["refusal_reasons"]))
        self.assertEqual(doc["analyzers"], {})   # no numbers at all on a refusal

    def test_different_schema_version_is_a_hard_refusal(self):
        doc = json.loads((self.d / "b.json").read_text())
        doc["schema_version"] = 999
        mutated = self.d / "b-schema.json"
        mutated.write_text(json.dumps(doc))
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(mutated), "--format", "json"])
        self.assertEqual(rc, 1)
        doc_out = json.loads(out)
        self.assertTrue(doc_out["refused"])
        self.assertTrue(any("schema_version differs" in r for r in doc_out["refusal_reasons"]))

    def test_refusal_still_shows_both_audit_sentences(self):
        b_other = self._with_audit_field(self.d / "b.json", adapter="cursor")
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(b_other)])
        self.assertEqual(rc, 1)
        self.assertIn("Report A", out)
        self.assertIn("Report B", out)
        self.assertIn("REFUSED", out)

    def test_a_refusal_is_not_silent_about_why(self):
        b_other = self._with_audit_field(self.d / "b.json", adapter="cursor")
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(b_other)])
        self.assertIn("not comparable", out)
        self.assertIn("claude-code", out)
        self.assertIn("cursor", out)


class LoudAnnotationTests(DiffFixture):
    def test_a_filtered_side_is_annotated_not_refused(self):
        rc, _, _ = _run(["run", str(self.d / "a"), "--adapter", "claude-code", "--format", "json",
                         "--since-day", "0", "--until-day", "0", "--out", str(self.d / "a-f.json")])
        self.assertEqual(rc, 0)
        rc, out, _ = _run(["diff", str(self.d / "a-f.json"), str(self.d / "b.json"),
                           "--format", "json"])
        self.assertEqual(rc, 0)     # NOT refused
        doc = json.loads(out)
        self.assertFalse(doc["refused"])
        self.assertTrue(any("SUBSET COMPARISON" in w for w in doc["comparability_warnings"]))
        # and it still produced real deltas alongside the warning
        self.assertTrue(any(e["status"] == "compared" for e in doc["analyzers"].values()))

    def test_filtered_warning_is_unmissable_in_markdown(self):
        rc, _, _ = _run(["run", str(self.d / "a"), "--adapter", "claude-code", "--format", "json",
                         "--since-day", "0", "--out", str(self.d / "a-f.json")])
        rc, out, _ = _run(["diff", str(self.d / "a-f.json"), str(self.d / "b.json")])
        self.assertEqual(rc, 0)
        self.assertIn("COMPARABILITY WARNING", out)
        self.assertIn("SUBSET COMPARISON", out)

    def test_analyzer_version_mismatch_is_annotated_and_that_one_analyzer_withheld(self):
        doc = json.loads((self.d / "b.json").read_text())
        doc["results"]["tempo"]["analyzer_version"] = 2
        mutated = self.d / "b-verbump.json"
        mutated.write_text(json.dumps(doc))
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(mutated), "--format", "json"])
        self.assertEqual(rc, 0)          # NOT a hard refusal
        result = json.loads(out)
        self.assertFalse(result["refused"])
        self.assertEqual(result["analyzers"]["tempo"]["status"], "version_mismatch")
        self.assertNotIn("deltas", result["analyzers"]["tempo"])
        self.assertTrue(any("VERSION MISMATCH" in w for w in result["comparability_warnings"]))
        # every OTHER shared analyzer is still diffed normally
        others = [n for n, e in result["analyzers"].items() if n != "tempo"]
        self.assertTrue(any(result["analyzers"][n]["status"] == "compared" for n in others))

    def test_version_mismatch_note_names_both_versions(self):
        doc = json.loads((self.d / "b.json").read_text())
        doc["results"]["tempo"]["analyzer_version"] = 2
        mutated = self.d / "b-verbump.json"
        mutated.write_text(json.dumps(doc))
        rc, out, _ = _run(["diff", str(self.d / "a.json"), str(mutated)])
        self.assertIn("analyzer_version 1", out)
        self.assertIn(" 2 ", out)
        self.assertIn("NOT DIFFED", out)

    def test_not_computable_analyzer_is_noted_not_diffed_as_zero(self):
        doc_a = json.loads((self.d / "a.json").read_text())
        doc_b = json.loads((self.d / "b.json").read_text())
        doc_a["results"]["tempo"] = {"error": "no deltas", "analyzer_version": 1}
        result = diffmod.compare(doc_a, doc_b)
        self.assertEqual(result["analyzers"]["tempo"]["status"], "not_computable")
        self.assertNotIn("deltas", result["analyzers"]["tempo"])


if __name__ == "__main__":
    unittest.main()
