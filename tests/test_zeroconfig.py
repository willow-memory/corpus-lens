"""Zero-config discovery: `corpuslens run` with no PATH and no `--adapter`.

The rule this holds: discovery is a GUESS about intent, so it must never
overclaim. It reports every conventional location it checked (found or not)
before reading anything, it names the adapter AND the path it chose inside
the report itself (not just terminal chatter), it never widens outside the
user's home directory or follows a symlink out of it, and an unreadable
location is reported rather than crashed on. The explicit two-argument form
must be entirely unaffected.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from corpuslens import ingest
from corpuslens.cli import main as cli_main

from test_pipeline import _cc_line, _write  # the same fixtures the spine uses


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(argv)
    return rc, out.getvalue(), err.getvalue()


class FakeHomeTests(unittest.TestCase):
    """Every test here runs with $HOME pointed at a scratch directory, so
    discovery never touches the real machine's actual ~/.claude, ~/.cursor or
    ~/.gemini."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        # Both spellings: `Path.home()` reads HOME on POSIX and USERPROFILE on
        # Windows, and a patch of only the first leaves the Windows leg of the
        # CI matrix discovering the runner's real home.
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def _write_claude_code(self, root, n=1):
        root.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            _write(
                root / f"s{i}.jsonl",
                [
                    _cc_line(
                        "user",
                        "build the parser for the config file please",
                        "2026-02-01T10:00:00Z",
                    ),
                    _cc_line("assistant", "Done. Should I add validation?", "2026-02-01T10:05:00Z"),
                ],
            )


class RegistrySeamTests(unittest.TestCase):
    """The seam itself: discovery is declared per adapter, not a hardcoded
    list in cli.py."""

    def test_the_three_directory_adapters_declare_their_own_convention(self):
        rows = {name: ingest.default_path_of(name) for name in ingest.discoverable()}
        self.assertEqual(rows["claude-code"], "~/.claude/projects")
        self.assertEqual(rows["cursor-store"], "~/.cursor/chats")
        self.assertEqual(rows["gemini-cli"], "~/.gemini/tmp")

    def test_an_adapter_with_no_declared_convention_is_not_offered(self):
        # `cursor` (plain jsonl) has no fixed on-disk home to guess at.
        self.assertNotIn("cursor", ingest.discoverable())
        self.assertIsNone(ingest.default_path_of("cursor"))

    def test_discoverable_is_a_pure_function_of_the_registry(self):
        # A new "dir" adapter can add itself with one decorator call and no
        # edit to cli.py -- simulate that here rather than editing cli.py.
        ingest.register_default_path("fake-adapter-for-test", "~/.fake/place")(lambda: None)
        try:
            self.assertIn("fake-adapter-for-test", ingest.discoverable())
        finally:
            del ingest._DEFAULT_PATH["fake-adapter-for-test"]


class NothingFoundTests(FakeHomeTests):
    def test_reports_every_location_checked_and_refuses_gracefully(self):
        rc, out, err = _run(["run"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")  # nothing ran -- no report to print on stdout
        for adapter, path in (
            ("claude-code", ".claude/projects"),
            ("cursor-store", ".cursor/chats"),
            ("gemini-cli", ".gemini/tmp"),
        ):
            self.assertIn(adapter, err)
            self.assertIn(path, err)
        self.assertIn("no corpus found", err.lower())
        self.assertIn("--adapter", err)  # points at the explicit form
        self.assertNotIn("Traceback", err)

    def test_a_present_but_empty_directory_is_named_present_not_missing(self):
        (self.home / ".claude" / "projects").mkdir(parents=True)
        rc, _, err = _run(["run"])
        self.assertEqual(rc, 1)
        self.assertIn("present, but no", err)


class DiscoveryAndRunTests(FakeHomeTests):
    def test_discovers_and_runs_a_single_corpus(self):
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        rc, out, err = _run(["run", "--format", "json"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        # the discovery report precedes the JSON document on stdout
        preamble, _, body = out.partition("{")
        self.assertIn("claude-code", preamble)
        self.assertIn("~/.claude/projects", preamble)
        self.assertNotIn(str(self.home), preamble)  # the declared form only, never resolved
        doc = json.loads("{" + body)
        self.assertEqual(doc["audit"]["adapter"], "claude-code")

    def test_the_chosen_path_is_named_in_the_report_itself(self):
        # Honesty requirement: the audit sentence already names the adapter
        # for every run; a DISCOVERED run additionally has to name the PATH
        # in that same sentence, because the user did not type it and a
        # reader of a saved report (not this terminal) still has to be able
        # to tell what was read.
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        rc, out, _ = _run(["run", "--format", "json"])
        doc = json.loads(out[out.index("{") :])
        self.assertEqual(doc["audit"]["discovered_path"], "~/.claude/projects")
        self.assertIn("~/.claude/projects", doc["audit"]["sentence"])
        self.assertIn("claude-code", doc["audit"]["sentence"])
        self.assertIn("No path or --adapter was given", doc["audit"]["sentence"])

    def test_the_reported_path_is_never_resolved_anywhere(self):
        # Wall finding (highest class, fixed on this branch): a resolved
        # discovered_path put the owner's real username in the same sentence
        # that claims nothing identifying left the wall. Regression: neither
        # the sentence, the JSON audit object, nor the full document may ever
        # contain the resolved $HOME the corpus actually lives under, in
        # either format and with or without --share.
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        home = str(Path.home().resolve())
        for extra in ([], ["--share"]):
            for fmt in ("json", "markdown"):
                rc, out, err = _run(["run", "--format", fmt] + extra)
                self.assertEqual(rc, 0)
                self.assertNotIn(home, out)
                self.assertNotIn(home, err)

    def test_share_mode_keeps_the_declared_path(self):
        # Decision made on this branch: once discovered_path can only ever
        # hold the declared, username-free constant (enforced by
        # AuditRecord.__setattr__), it carries no more identifying weight
        # than the `adapter` field beside it in the same sentence -- and
        # `adapter` has never been stripped by --share. So --share keeps it.
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        rc, out, _ = _run(["run", "--format", "json", "--share"])
        self.assertEqual(rc, 0)
        doc = json.loads(out[out.index("{") :])
        self.assertEqual(doc["audit"]["discovered_path"], "~/.claude/projects")
        self.assertNotIn(str(self.home), doc["audit"]["sentence"])
        self.assertNotIn(str(self.home), json.dumps(doc))

    def test_explicit_run_never_sets_discovered_path(self):
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        rc, out, _ = _run(["run", str(d), "--adapter", "claude-code", "--format", "json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertIsNone(doc["audit"]["discovered_path"])
        self.assertNotIn("No path or --adapter was given", doc["audit"]["sentence"])

    def test_picks_the_largest_corpus_and_says_so(self):
        cc = self.home / ".claude" / "projects"
        self._write_claude_code(cc, n=1)
        cs1 = self.home / ".cursor" / "chats" / "w" / "a1"
        cs2 = self.home / ".cursor" / "chats" / "w" / "a2"
        cs1.mkdir(parents=True)
        cs2.mkdir(parents=True)
        (cs1 / "store.db").write_bytes(b"")
        (cs2 / "store.db").write_bytes(b"")

        rc, out, err = _run(["run"])
        # cursor-store "wins" the count (2 files > 1), gets run, and both its
        # store.db files are empty so ingestion legitimately finds nothing --
        # the point of this test is WHICH adapter was picked and that the
        # choice was announced, not that the run succeeds.
        self.assertIn("cursor-store", out)
        self.assertIn("claude-code", out)  # the runner-up is still named
        self.assertIn("LARGEST", out)
        self.assertIn("~/.cursor/chats", out)  # the declared form, not a resolved path
        self.assertNotIn(str(self.home), out)
        self.assertEqual(rc, 1)
        self.assertIn("cursor-store", err)  # the actual run that followed

    def test_only_one_of_path_or_adapter_is_rejected(self):
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        rc1, _, err1 = _run(["run", "--adapter", "claude-code"])
        self.assertEqual(rc1, 2)
        self.assertIn("--adapter", err1)
        rc2, _, err2 = _run(["run", str(d)])
        self.assertEqual(rc2, 2)
        self.assertIn("neither", err2)

    def test_explicit_two_argument_form_is_unaffected(self):
        # Same corpus, both ways -- the explicit form's own report (adapter,
        # counts, sentence) must be byte-identical to a run made before this
        # feature existed: no `discovered_path` clause, no preamble.
        d = self.home / "somewhere" / "else"
        self._write_claude_code(d)
        rc, out, err = _run(["run", str(d), "--adapter", "claude-code"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertNotIn("No path or --adapter was given", out)
        self.assertNotIn("looking in conventional locations", out)


class ContainmentTests(FakeHomeTests):
    def test_refuses_a_declared_path_that_symlinks_outside_home(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        real = Path(outside.name) / "real_projects"
        self._write_claude_code(real)
        link = self.home / ".claude" / "projects"
        link.parent.mkdir(parents=True)
        os.symlink(real, link)

        rc, out, err = _run(["run"])
        self.assertEqual(rc, 1)
        self.assertIn("outside the home directory", err)
        self.assertNotIn(str(real), err)  # the refused path is named, not walked

    def test_an_unreadable_directory_is_reported_not_crashed_on(self):
        # Simulated rather than a real chmod: the test suite may run as root,
        # which bypasses permission bits entirely, so a real chmod(0o000)
        # would not exercise this path at all. `os.walk` raising is exactly
        # what a genuinely permission-denied directory looks like to
        # `_count_files_no_symlinks`.
        d = self.home / ".claude" / "projects"
        self._write_claude_code(d)
        from corpuslens import cli

        with mock.patch.object(cli.os, "walk", side_effect=PermissionError("denied")):
            rc, out, err = _run(["run"])
        self.assertEqual(rc, 1)
        self.assertIn("unreadable", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()


class DiscoveredFailurePathTests(unittest.TestCase):
    """A discovered run that FAILS must not print what the successful one hid.

    The success line says `~/.claude/projects`. Until this test, the failure
    line for the same corpus said `/home/<name>/.claude/projects`, because the
    shared `_empty_message` echoes whatever path it was given. On an explicit
    run that is right — the user typed it. On a discovered run they did not,
    and the tool has already demonstrated it knows the username-free form.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        d = self.home / ".claude" / "projects"
        d.mkdir(parents=True)
        (d / "junk.jsonl").write_text("not json at all\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_discovered(self):
        out, err = io.StringIO(), io.StringIO()
        home = self.home
        with (
            mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}),
            mock.patch.object(Path, "home", staticmethod(lambda: home)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli_main(["run"])
        return code, out.getvalue() + err.getvalue()

    def test_a_failing_discovered_run_never_prints_the_resolved_home(self):
        code, text = self._run_discovered()
        self.assertNotEqual(code, 0)
        self.assertNotIn(str(self.home), text)
        self.assertIn("~/.claude/projects", text)
