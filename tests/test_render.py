"""The report as something to read.

The rule these hold: presentation must never become a second, friendlier set
of numbers. Every sentence the renderer prints comes from the same result dict
as the JSON under it, an analyzer that could not compute says so in words
rather than rendering an empty section that reads as a zero, and a sample too
small to carry a decimal is labelled as such.
"""
import json
import unittest

from corpuslens.analyze import all_analyzers
from corpuslens.guard import AuditRecord
from corpuslens.render import RUBRIC_SCOPE_NOTE, SMALL_N, json_report, markdown


def _audit(**kw):
    return AuditRecord(profile="default", **kw)


class HeadlineTests(unittest.TestCase):
    def test_findings_list_leads_the_report(self):
        md = markdown({"a": {"headline": "You did the thing 40% of the time.", "n": 100,
                             "denominator": "turns", "x": 1}}, _audit())
        self.assertIn("## What this run found", md)
        self.assertLess(md.index("What this run found"), md.index("## a"))
        self.assertIn("- **a** — You did the thing 40% of the time.", md)

    def test_headline_and_denominator_appear_in_the_section(self):
        md = markdown({"a": {"headline": "Forty percent.", "n": 100,
                             "denominator": "turns with >=12 characters"}}, _audit())
        self.assertIn("**Forty percent.**", md)
        self.assertIn("Out of turns with >=12 characters; n = 100.", md)

    def test_audit_sentence_still_comes_first(self):
        md = markdown({"a": {"headline": "h", "n": 1}}, _audit())
        self.assertLess(md.index("left the wall"), md.index("What this run found"))

    def test_a_result_with_no_headline_still_renders_its_numbers(self):
        md = markdown({"a": {"denominator": "turns", "count_of_things": 7}}, _audit())
        self.assertIn("## a", md)
        self.assertIn("count_of_things", md)


class RubricScopeTests(unittest.TestCase):
    """GRADING.md poses ten questions; this battery answers (fully or partly)
    only the first four. The report must say that once, plainly, naming the
    rest — see IDEAS.md, "Say which rubric question each analyzer answers"."""

    def test_rubric_scope_note_appears_after_the_audit_sentence(self):
        md = markdown({"a": {"headline": "h", "n": 1}}, _audit())
        # the clause naming how many analyzers map to no question is computed from
        # the registry, so the constant is a template — compare the fixed halves
        head, tail = RUBRIC_SCOPE_NOTE.split("{unmapped_clause}")
        self.assertIn(head.strip(), md)
        self.assertIn(tail.strip(), md)
        self.assertLess(md.index("left the wall"), md.index(head.strip()))
        self.assertLess(md.index(tail.strip()), md.index("What this run found"))

    def test_rubric_scope_note_names_the_unmeasurable_questions(self):
        # The exact numbers matter — this is the sentence that stops the
        # rubric reading like a promise the tool did not keep.
        for marker in ("5-8", "9-10", "not corpus-measurable"):
            self.assertIn(marker, RUBRIC_SCOPE_NOTE)

    def test_grading_question_is_shown_in_its_section(self):
        md = markdown({"a": {"headline": "h", "n": 1, "grading_question": "question 1"}}, _audit())
        self.assertIn("GRADING.md: question 1.", md)

    def test_grading_question_is_shown_even_when_not_computable(self):
        md = markdown({"a": {"error": "no data", "grading_question": "question 1"}}, _audit())
        self.assertIn("GRADING.md: question 1.", md)

    def test_grading_question_is_omitted_from_the_raw_json_block(self):
        md = markdown({"a": {"headline": "h", "n": 1, "grading_question": "question 1"}}, _audit())
        block = json.loads(md.split("```json")[1].split("```")[0])
        self.assertNotIn("grading_question", block)

    def test_every_registered_analyzer_declares_a_grading_question(self):
        for a in all_analyzers():
            with self.subTest(analyzer=a.name):
                self.assertIsInstance(a.grading_question, str)
                self.assertTrue(a.grading_question.strip())

    def test_register_rejects_a_blank_grading_question(self):
        from corpuslens.analyze import register
        with self.assertRaises(ValueError):
            register("bad", claims=("tempo",), denominator="turns", version=1,
                      grading_question="  ")(lambda ev: {})

    def test_a_partial_mapping_says_part_of(self):
        # thread_shape and thread_span only partly cover GRADING.md question 4
        # (no >=30-day bucket, no "productive return" check) — the declaration
        # must say so rather than claim the whole question.
        by_name = {a.name: a for a in all_analyzers()}
        for name in ("thread_shape", "thread_span"):
            self.assertIn("part of question 4", by_name[name].grading_question)


class ReferenceProvenanceTests(unittest.TestCase):
    """Every analyzer compares the reader to `measured_director_n1` (or a
    sibling key) — the author's own corpus, one person. The rendered report
    must say so beside the comparison, and keep the named population
    aggregates (WildChat, OASST) distinct from it — see IDEAS.md, "Say whose
    corpus the reference is"."""

    def test_the_n1_reference_is_labelled_one_person(self):
        res = {"headline": "h", "n": 1,
               "reference": {"measured_director": "96.8% mid-task"}}
        md = markdown({"a": res}, _audit())
        self.assertIn("measured_director", md)
        self.assertIn("the author's own corpus (N=1)", md)
        self.assertIn("a gap from this reference is a gap from one person, not a population", md)

    def test_population_aggregates_are_not_relabelled_as_n1(self):
        res = {"headline": "h", "n": 1,
               "reference": {"wildchat_coding_population": {"authored_pct": 14.5},
                             "oasst_general_chat": {"delib_pct": 7.3}}}
        md = markdown({"a": res}, _audit())
        # both population rows print, neither gets the N=1 sentence attached
        wildchat_line = next(l for l in md.splitlines() if "wildchat_coding_population" in l)
        oasst_line = next(l for l in md.splitlines() if "oasst_general_chat" in l)
        self.assertNotIn("N=1", wildchat_line)
        self.assertNotIn("N=1", oasst_line)

    def test_classifier_error_sentence_appears_once_beside_an_n1_reference(self):
        res = {"headline": "h", "n": 1,
               "reference": {"measured_director": "x", "measured_cursor_note": "y"}}
        md = markdown({"a": res}, _audit())
        self.assertEqual(md.count("corpuslens label"), 1)
        self.assertIn("corpuslens score", md)

    def test_no_reference_means_no_classifier_error_sentence(self):
        md = markdown({"a": {"headline": "h", "n": 1}}, _audit())
        self.assertNotIn("corpuslens label", md)

    def test_reference_is_omitted_from_the_raw_json_block(self):
        res = {"headline": "h", "n": 1, "reference": {"measured_director": "x"}}
        md = markdown({"a": res}, _audit())
        block = json.loads(md.split("```json")[1].split("```")[0])
        self.assertNotIn("reference", block)

    def test_json_renderer_keeps_reference_and_grading_question_verbatim(self):
        res = {"headline": "h", "n": 1, "grading_question": "question 1",
               "reference": {"measured_director": "x"}}
        doc = json.loads(json_report({"a": res}, _audit()))
        self.assertEqual(doc["results"]["a"]["grading_question"], "question 1")
        self.assertEqual(doc["results"]["a"]["reference"], {"measured_director": "x"})


class NotComputableTests(unittest.TestCase):
    def test_error_is_stated_in_words_not_an_empty_section(self):
        md = markdown({"tempo": {"denominator": "turns with a delta",
                                 "error": "no within-day tempo deltas in this corpus"}}, _audit())
        self.assertIn("**Not computable on this corpus.**", md)
        self.assertIn("no within-day tempo deltas", md)
        self.assertIn("Denominator would be: turns with a delta.", md)

    def test_error_also_appears_in_the_findings_list(self):
        md = markdown({"tempo": {"error": "no prompt clock here"}}, _audit())
        self.assertIn("- **tempo** — not computable on this corpus. no prompt clock here", md)

    def test_an_error_never_renders_as_a_zero(self):
        md = markdown({"tempo": {"error": "no deltas"}}, _audit())
        self.assertNotIn("n = 0", md)
        self.assertNotIn("0.0%", md)


class SmallSampleTests(unittest.TestCase):
    def test_small_n_is_labelled(self):
        md = markdown({"a": {"headline": "h", "n": SMALL_N - 1, "denominator": "turns"}}, _audit())
        self.assertIn(f"Small sample (n = {SMALL_N - 1})", md)
        self.assertIn("read the direction, not the decimal", md)

    def test_a_sample_at_the_threshold_is_not_labelled(self):
        md = markdown({"a": {"headline": "h", "n": SMALL_N, "denominator": "turns"}}, _audit())
        self.assertNotIn("Small sample", md)

    def test_zero_n_is_not_called_a_small_sample(self):
        # n == 0 is "nothing to say", not "a little to say" — an analyzer with
        # no denominator left should have returned an error instead.
        md = markdown({"a": {"headline": "h", "n": 0, "denominator": "turns"}}, _audit())
        self.assertNotIn("Small sample", md)


class NoSecondSetOfNumbersTests(unittest.TestCase):
    def test_every_number_survives_into_the_json_block(self):
        res = {"headline": "h", "reading": "r", "vs_coding_population": "v", "n": 40,
               "denominator": "turns", "pct": 12.5, "count": 3, "nested": {"ref": 1.0}}
        md = markdown({"a": res}, _audit())
        block = json.loads(md.split("```json")[1].split("```")[0])
        for key, val in res.items():
            if isinstance(val, str) and key in ("headline", "reading", "vs_coding_population"):
                continue          # rendered verbatim above; omitted, not dropped
            self.assertEqual(block[key], val)

    def test_only_already_rendered_strings_are_omitted(self):
        md = markdown({"a": {"headline": "H-TEXT", "reading": "R-TEXT", "n": 40,
                             "denominator": "turns"}}, _audit())
        self.assertEqual(md.count("H-TEXT"), 2)    # findings list + section headline
        self.assertEqual(md.count("R-TEXT"), 1)    # the quote only
        block = json.loads(md.split("```json")[1].split("```")[0])
        self.assertNotIn("headline", block)
        self.assertNotIn("reading", block)

    def test_json_renderer_keeps_the_presentation_fields(self):
        # the machine-readable form is the WHOLE result — it does not inherit
        # the markdown renderer's omissions
        doc = json.loads(json_report({"a": {"headline": "h", "reading": "r", "n": 1}}, _audit()))
        self.assertEqual(doc["results"]["a"]["headline"], "h")
        self.assertEqual(doc["results"]["a"]["reading"], "r")


class AnalyzerContractTests(unittest.TestCase):
    """Every registered analyzer must be renderable as a finding."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from corpuslens import ingest
        from test_pipeline import _cc_line, _write
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        _write(d / "s1.jsonl", [
            _cc_line("user", "build the parser for the config file please", "2026-02-01T10:00:00Z"),
            _cc_line("assistant", "Done. Should I add validation, or keep it minimal?", "2026-02-01T10:05:00Z"),
            _cc_line("user", "it still fails on empty input, fix that", "2026-02-01T10:20:00Z"),
            _cc_line("user", "lets talk about the tradeoffs for the cache layer", "2026-02-04T09:00:00Z"),
        ])
        self.events, _, _ = ingest.get("claude-code")(str(d))

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_analyzer_returns_a_headline_and_an_n(self):
        for a in all_analyzers():
            with self.subTest(analyzer=a.name):
                res = a.run(self.events)
                if "error" in res:
                    continue                      # the documented alternative
                self.assertIn("headline", res, f"{a.name} has no headline")
                self.assertTrue(res["headline"].strip().endswith("."),
                                f"{a.name}'s headline is not a sentence")
                self.assertIsInstance(res.get("n"), int, f"{a.name} has no integer n")
                self.assertGreater(res["n"], 0)

    def test_no_headline_states_a_verdict_about_the_person(self):
        # the claim ontology forbids person-shaped claims in the data; the
        # PROSE must not smuggle one back in through a friendly sentence.
        banned = ("you are", "you're", "good at", "bad at", "better than", "worse than")
        for a in all_analyzers():
            res = a.run(self.events)
            text = (res.get("headline", "") + " " + res.get("reading", "")).lower()
            for phrase in banned:
                with self.subTest(analyzer=a.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_rendered_report_carries_no_content_or_anchor(self):
        results = {a.name: {"denominator": a.denominator, **a.run(self.events)}
                   for a in all_analyzers()}
        md = markdown(results, _audit(n_events=len(self.events)))
        for leak in ("2026-02-01", "2026", ".jsonl", "cache layer", "mastery.py"):
            self.assertNotIn(leak, md)


if __name__ == "__main__":
    unittest.main()


class PackagingTests(unittest.TestCase):
    """The version has exactly one source of truth: the git tag."""

    @staticmethod
    def _repo_file(name):
        # Relative to THIS file, not the cwd — the suite must pass from
        # anywhere, and `unittest discover -s tests` does not promise a cwd.
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8")

    def test_version_is_a_string_and_never_a_literal_in_the_package(self):
        import corpuslens
        self.assertIsInstance(corpuslens.__version__, str)
        self.assertTrue(corpuslens.__version__)
        src = self._repo_file("corpuslens/__init__.py")
        self.assertNotIn('__version__ = "0.', src)   # no hard-coded release number

    def test_the_distribution_name_matches_everywhere_it_is_written(self):
        # Four places must agree or the publish fails at upload, where the error
        # is unhelpful: pyproject, __init__'s metadata lookup, release-please's
        # package-name, and the artifact regex in the release workflow (which
        # sees the PEP 625 underscored form).
        import json
        self.assertIn('name = "willow-corpus-lens"', self._repo_file("pyproject.toml"))
        self.assertIn('_version("willow-corpus-lens")',
                      self._repo_file("corpuslens/__init__.py"))
        cfg = json.loads(self._repo_file("release-please-config.json"))
        self.assertEqual(cfg["packages"]["."]["package-name"], "willow-corpus-lens")
        self.assertIn("willow_corpus_lens-", self._repo_file(".github/workflows/release.yml"))

    def test_pyproject_declares_the_version_dynamic(self):
        # hatch-vcs derives it from the tag; a literal here would be a second
        # copy that drifts the moment a tag is cut.
        text = self._repo_file("pyproject.toml")
        self.assertIn('dynamic = ["version"]', text)
        self.assertNotIn('\nversion = "', text)

    def test_release_manifest_and_config_agree_on_the_package_name(self):
        import json
        cfg = json.loads(self._repo_file("release-please-config.json"))
        manifest = json.loads(self._repo_file(".release-please-manifest.json"))
        pkg = cfg["packages"]["."]
        # the DISTRIBUTION name, which must equal the PyPI trusted-publishing
        # project exactly; the import package and console script stay `corpuslens`
        self.assertEqual(pkg["package-name"], "willow-corpus-lens")
        self.assertEqual(pkg["release-type"], "simple")   # hatch-vcs owns the version
        self.assertIn(".", manifest)
