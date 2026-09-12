"""The guardian-consent seam: a subject who is not the owner.

Three things are held here, and every one of them is a refusal test first:

1. The vendored core is the fleet's copy, byte for byte. Its code body's hash
   is pinned to the SAME value willow-mcp's own tests pin, so the two repos
   check each other without either importing the other. Editing the copy in
   place is what the pin refuses.
2. The gate is fail-closed on every path the core names — no store, no
   record, pending, revoked, a tampered chain — and it runs BEFORE ingest,
   so a refused subject's corpus is never opened.
3. Owner == subject is untouched: a run without `--subject` produces the
   exact sentence it always has, consults no store, and writes no row.

And two things the seam deliberately leaves out are pinned as absences: the
subject's id never reaches a report, and a consent grant for
`person_inference` does not admit a person-claim analyzer.
"""

import ast
import hashlib
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from corpuslens import subject_consent as binding
from corpuslens.analyze import Analyzer
from corpuslens.cli import main as cli_main
from corpuslens.consent import core
from corpuslens.guard import DEFAULT_PROFILE, Guard
from corpuslens.model import Quarantine

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent / "corpuslens" / "consent"
SAMPLE = HERE.parent / "examples" / "sample-corpus"

#: willow-mcp tests/test_subject_consent.py::EXPECTED_BODY_SHA256["core.py"].
#: If this changes, willow-mcp re-synced from the canonical
#: safe-app-store libs/subject-consent — re-vendor from willow-mcp and paste
#: the value its test prints. If only THIS repo's hash moved, the vendored
#: copy was edited in place, which it must not be.
WILLOW_MCP_PIN = "6a9348177ab25312b0674d0cf2d9417504dfa6323b21083b6c34a87660690e98"
_MARKER = "from __future__ import annotations"


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


# ── the three source scans, as helpers so they can be planted ──────────────
# Each was an inline check in a test body until tests/test_scans_fire.py's
# meta-scan reported it: a scan written inline has nothing to name and
# nothing to plant, so it can never be shown to fire. Factored out, each has
# a planted-violation test below.


def _non_stdlib_imports(source):
    """Every absolute import in `source` whose top-level module is not in the
    standard library — the reason a stdlib-only-by-charter package can take
    the vendored core at all."""
    stdlib = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.split(".")[0] not in stdlib]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if (node.module or "").split(".")[0] not in stdlib:
                offenders.append(node.module)
    return offenders


def _vendored_body_names(path, needle):
    """Whether the vendored body of `path` — from `_MARKER` to EOF, the part
    pinned to willow-mcp — names `needle`. The local docstring above the
    marker is not the body and may say what it likes."""
    text = path.read_text(encoding="utf-8")
    return needle in text[text.index(_MARKER) :]


#: The two sub-parser registrations that bound the `run` block. Matched with
#: optional whitespace after the paren, so a formatter wrapping the call onto
#: several lines does not move the anchor.
_RUN_PARSER = re.compile(r'sub\.add_parser\(\s*"run"')
_DOCTOR_PARSER = re.compile(r'sub\.add_parser\(\s*"doctor"')


def _run_parser_mentions(cli_path, needle):
    """Whether cli.py's `run` sub-parser block — the text between
    `sub.add_parser("run"` and `sub.add_parser("doctor"` — carries `needle`.
    Read from the source, because argparse exits on --help."""
    src = cli_path.read_text(encoding="utf-8")
    block = src[_RUN_PARSER.search(src).start() : _DOCTOR_PARSER.search(src).start()]
    return needle in block


class VendoredCopyTests(unittest.TestCase):
    def test_core_body_matches_willow_mcp_pin(self):
        text = (PKG / "core.py").read_text(encoding="utf-8")
        body = text[text.index(_MARKER) :]
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), WILLOW_MCP_PIN)

    def test_core_imports_stdlib_only(self):
        """The reason a stdlib-only-by-charter package can take this at all."""
        self.assertEqual(_non_stdlib_imports((PKG / "core.py").read_text(encoding="utf-8")), [])

    def test_planted_third_party_import_is_caught(self):
        self.assertEqual(
            sorted(
                _non_stdlib_imports(
                    "import json\nimport requests\nfrom yaml import safe_load\n"
                    "from . import sibling\n"
                )
            ),
            ["requests", "yaml"],  # the relative import is the package's own
        )

    def test_core_never_imports_corpuslens(self):
        self.assertFalse(_vendored_body_names(PKG / "core.py", "corpuslens"))

    def test_planted_corpuslens_reference_in_the_body_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "core.py"
            planted.write_text(
                '"""A docstring may say corpuslens; the body may not."""\n'
                f"{_MARKER}\nimport corpuslens\n",
                encoding="utf-8",
            )
            self.assertTrue(_vendored_body_names(planted, "corpuslens"))
            planted.write_text(
                '"""A docstring may say corpuslens; the body may not."""\n'
                f"{_MARKER}\nimport json\n",
                encoding="utf-8",
            )
            self.assertFalse(_vendored_body_names(planted, "corpuslens"))

    def test_scope_names_line_up_with_the_guard(self):
        """Same name on purpose, wired on purpose NOT at all — see binding."""
        from corpuslens.guard import KNOWN_CAPABILITIES

        self.assertIn("person_inference", core.SCOPES)
        self.assertIn("person_inference", KNOWN_CAPABILITIES)
        self.assertEqual(binding.SCOPE, "process_analysis")


class GateRefusalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "consent"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_store_is_refused(self):
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "s1")

    def test_empty_subject_is_refused(self):
        self.store.mkdir()
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "   ")

    def test_no_record_is_refused(self):
        binding.grant(self.store, "someone-else", "guardian")
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "s1")

    def test_other_scope_does_not_open_this_one(self):
        core.grant(self.store, "s1", "kb_promotion", "guardian")
        core.grant(self.store, "s1", "person_inference", "guardian")
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "s1")

    def test_revoked_is_refused_and_the_grant_is_kept_as_history(self):
        binding.grant(self.store, "s1", "guardian")
        binding.require_grant(self.store, "s1")  # must not raise
        binding.revoke(self.store, "s1", "guardian")
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "s1")
        rows = (self.store / "consent.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(r)["status"] for r in rows], ["granted", "revoked"])

    def test_tampered_chain_is_refused(self):
        binding.grant(self.store, "s1", "guardian")
        p = self.store / "consent.jsonl"
        row = json.loads(p.read_text().splitlines()[0])
        row["granted_by"] = "nobody"  # edit without re-hashing
        p.write_text(json.dumps(row, sort_keys=True) + "\n")
        with self.assertRaises(binding.SubjectRefused) as cm:
            binding.require_grant(self.store, "s1")
        self.assertIn("verification", str(cm.exception))

    def test_truncated_chain_is_refused(self):
        binding.grant(self.store, "s1", "guardian")
        binding.revoke(self.store, "s1", "guardian")
        p = self.store / "consent.jsonl"
        p.write_text(p.read_text().splitlines()[0] + "\n")  # drop the revocation
        with self.assertRaises(binding.SubjectRefused):
            binding.require_grant(self.store, "s1")

    def test_refusal_never_echoes_the_subject(self):
        for sid in ("real-child-name", "s1"):
            with self.assertRaises(binding.SubjectRefused) as cm:
                binding.require_grant(self.store, sid)
            self.assertNotIn(sid, str(cm.exception))


class RunGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "consent"

    def tearDown(self):
        self.tmp.cleanup()

    def test_refused_subject_means_nothing_is_read(self):
        opened = []
        real_open = pathlib.Path.open

        def spy(self_, *a, **kw):
            opened.append(str(self_))
            return real_open(self_, *a, **kw)

        pathlib.Path.open = spy
        try:
            rc, out, err = _run(
                [
                    "run",
                    str(SAMPLE),
                    "--adapter",
                    "claude-code",
                    "--subject",
                    "s1",
                    "--consent-store",
                    str(self.store),
                ]
            )
        finally:
            pathlib.Path.open = real_open
        self.assertEqual(rc, 4)
        self.assertIn("consent refused", err)
        self.assertEqual(out, "")
        self.assertEqual(
            [p for p in opened if str(SAMPLE) in p], [], "a refused subject's files were opened"
        )
        # positive control: the same spy DOES see an owner run open the corpus,
        # so the empty list above is evidence and not a spy on the wrong call.
        pathlib.Path.open = spy
        try:
            rc, _, _ = _run(["run", str(SAMPLE), "--adapter", "claude-code"])
        finally:
            pathlib.Path.open = real_open
        self.assertEqual(rc, 0)
        self.assertTrue(any(str(SAMPLE) in p for p in opened), "the spy never saw a read")

    def test_half_a_consent_object_is_refused(self):
        rc, _, err = _run(["run", str(SAMPLE), "--adapter", "claude-code", "--subject", "s1"])
        self.assertEqual(rc, 2)
        self.assertIn("go together", err)
        rc, _, err = _run(
            ["run", str(SAMPLE), "--adapter", "claude-code", "--consent-store", str(self.store)]
        )
        self.assertEqual(rc, 2)

    def test_subject_cannot_ride_along_with_discovery(self):
        rc, _, err = _run(["run", "--subject", "s1", "--consent-store", str(self.store)])
        self.assertEqual(rc, 2)
        self.assertIn("auto-discovery", err)

    def test_granted_subject_runs_discloses_and_says_so_without_naming(self):
        binding.grant(self.store, "s1-opaque", "guardian")
        rc, out, err = _run(
            [
                "run",
                str(SAMPLE),
                "--adapter",
                "claude-code",
                "--format",
                "json",
                "--subject",
                "s1-opaque",
                "--consent-store",
                str(self.store),
            ]
        )
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["audit"]["subject_consent"], "process_analysis")
        self.assertIn("another person's", doc["audit"]["sentence"])
        self.assertIn("identifier is not in this report", doc["audit"]["sentence"])
        self.assertNotIn("s1-opaque", out)
        # the report addresses nobody as "you" — it is someone else's corpus
        for name, res in doc["results"].items():
            for field in ("headline", "reading"):
                v = res.get(field, "")
                self.assertNotRegex(v, r"\byou\b|\byour\b", f"{name}.{field}: {v!r}")
        # counts-only row on the subject's own record; the run's numbers are not on it
        rows = core.read_disclosures(self.store, "s1-opaque")
        self.assertEqual([r["action"] for r in rows], ["consent granted", "corpuslens run"])
        self.assertEqual(
            rows[-1]["detail"],
            f"scope=process_analysis adapter=claude-code "
            f"events={doc['audit']['n_events']} dropped={doc['audit']['n_dropped']}",
        )

    def test_human_reference_points_survive_a_named_subject(self):
        """Only the pronouns go: the subject may well be a human, and a human
        reference is still the right comparison. Withholding stays the job of
        the INFERRED-subject lens, not of consent."""
        from corpuslens.guard import AuditRecord
        from corpuslens.render import _apply_subject_lens

        a = AuditRecord(profile="default")
        a.subject, a.subject_consent = "human", "process_analysis"
        res = {"x": {"headline": "your prompts arrive mid-task", "reference": {"n1": 1}}}
        out = _apply_subject_lens(res, a)
        self.assertNotIn("your", out["x"]["headline"])
        self.assertIn("reference", out["x"])

    def test_doctor_is_gated_and_disclosed_too(self):
        rc, _, err = _run(
            [
                "doctor",
                str(SAMPLE),
                "--adapter",
                "claude-code",
                "--subject",
                "s1",
                "--consent-store",
                str(self.store),
            ]
        )
        self.assertEqual(rc, 4)
        binding.grant(self.store, "s1", "guardian")
        rc, out, _ = _run(
            [
                "doctor",
                str(SAMPLE),
                "--adapter",
                "claude-code",
                "--format",
                "json",
                "--subject",
                "s1",
                "--consent-store",
                str(self.store),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["subject_consent"], "process_analysis")
        self.assertNotIn("s1", json.loads(out).values())
        self.assertEqual(core.read_disclosures(self.store, "s1")[-1]["action"], "corpuslens doctor")

    def test_owner_run_is_untouched(self):
        rc, out, _ = _run(["run", str(SAMPLE), "--adapter", "claude-code", "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertIsNone(doc["audit"]["subject_consent"])
        self.assertNotIn("another person's", doc["audit"]["sentence"])
        self.assertNotIn("consent", doc["audit"]["sentence"])
        self.assertFalse(self.store.exists(), "an owner run must not create a consent store")


class ConsentCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = str(Path(self.tmp.name) / "consent")

    def tearDown(self):
        self.tmp.cleanup()

    def test_grant_needs_a_grantor(self):
        rc, _, err = _run(["consent", "grant", "s1", "--store", self.store])
        self.assertEqual(rc, 2)
        self.assertIn("--by", err)
        self.assertFalse(Path(self.store).exists())

    def test_grant_status_revoke_status(self):
        rc, out, _ = _run(["consent", "grant", "s1", "--store", self.store, "--by", "guardian"])
        self.assertEqual(rc, 0)
        rc, out, _ = _run(["consent", "status", "s1", "--store", self.store, "--format", "json"])
        st = json.loads(out)
        self.assertTrue(st["scopes"]["process_analysis"])
        self.assertFalse(st["scopes"]["person_inference"])
        self.assertEqual(st["disclosure_chain"], "verified")
        rc, _, _ = _run(["consent", "revoke", "s1", "--store", self.store, "--by", "guardian"])
        self.assertEqual(rc, 0)
        rc, out, _ = _run(["consent", "status", "s1", "--store", self.store, "--format", "json"])
        self.assertFalse(json.loads(out)["scopes"]["process_analysis"])
        self.assertEqual(
            [d["action"] for d in json.loads(out)["disclosures"]],
            ["consent granted", "consent revoked"],
        )

    def test_grant_refuses_to_extend_a_tampered_chain(self):
        _run(["consent", "grant", "s1", "--store", self.store, "--by", "guardian"])
        p = Path(self.store) / "consent.jsonl"
        p.write_text("")  # emptied, anchor left behind
        rc, _, err = _run(["consent", "grant", "s2", "--store", self.store, "--by", "guardian"])
        self.assertEqual(rc, 4)
        self.assertIn("ChainTamperError", err)


class WhatIsDeliberatelyNotWiredTests(unittest.TestCase):
    def test_a_person_inference_grant_does_not_admit_a_person_claim(self):
        """Consent is necessary, never sufficient. The Guard's own gate is the
        only thing that admits a person-claim analyzer, and the default
        profile still grants nothing."""
        with tempfile.TemporaryDirectory() as d:
            core.grant(d, "s1", "person_inference", "guardian")
            self.assertTrue(core.permitted(d, "s1", "person_inference"))
            g = Guard(Quarantine(), DEFAULT_PROFILE)
            a = Analyzer(
                name="life",
                claims=("life_partition",),
                denominator="d",
                run=lambda ev: {},
                version=1,
                grading_question="none",
            )
            self.assertFalse(g.admit(a))
            self.assertTrue(any("person claim" in s for s in g.audit.analyzers_refused))

    def test_run_has_no_flag_that_grants(self):
        """`consent grant` is the only door; `run`'s parser only ever LOOKS UP
        a grant. Read from the source: argparse exits on --help."""
        cli = HERE.parent / "corpuslens" / "cli.py"
        self.assertFalse(_run_parser_mentions(cli, "--grant"))
        self.assertFalse(_run_parser_mentions(cli, "consentmod.grant"))
        self.assertTrue(
            _run_parser_mentions(cli, "grant must verify")
        )  # the flag's help says what it checks

    def test_planted_grant_flag_on_run_is_caught(self):
        """And the slice is what makes it a `run` check: the same flag on the
        `doctor` parser is not `run`'s and must not be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "cli.py"
            planted.write_text(
                'run = sub.add_parser("run")\nrun.add_argument("--grant")\n'
                'doc = sub.add_parser("doctor")\n',
                encoding="utf-8",
            )
            self.assertTrue(_run_parser_mentions(planted, "--grant"))
            planted.write_text(
                'run = sub.add_parser("run")\n'
                'doc = sub.add_parser("doctor")\ndoc.add_argument("--grant")\n',
                encoding="utf-8",
            )
            self.assertFalse(_run_parser_mentions(planted, "--grant"))
            # and the anchor survives a formatter wrapping the registration
            planted.write_text(
                'run = sub.add_parser(\n    "run",\n    help="x",\n)\n'
                'run.add_argument("--grant")\n'
                'doc = sub.add_parser(\n    "doctor",\n)\n',
                encoding="utf-8",
            )
            self.assertTrue(_run_parser_mentions(planted, "--grant"))


if __name__ == "__main__":
    unittest.main()
