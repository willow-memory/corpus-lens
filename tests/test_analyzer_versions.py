"""Per-analyzer SEMANTIC versions — what a number means, not what shape the
document is (that's `render.SCHEMA_VERSION`, covered in test_render.py).

The rule this file exists to hold: a `version` nobody remembers to bump is
worse than none, because it looks like a real comparability guarantee. Every
analyzer whose result depends on a classifier regex or a numeric threshold
pins a `semantic_hash` computed from those exact literal inputs. If a future
edit changes one of those inputs (a regex pattern, a threshold), the LIVE hash
recomputed here stops matching the pinned literal in the analyzer's own module
— and this test fails, on the change, before the analyzer's `version` field
has quietly gone stale. The fix is never "update the hash" alone: it is "bump
`version`, THEN update the hash" (see corpuslens/analyze/__init__.py).
"""

import unittest

from corpuslens.analyze import all_analyzers, register, semantic_hash
from corpuslens.analyze import composition as composition_mod
from corpuslens.analyze import tempo as tempo_mod
from corpuslens.classifiers import AUTHORED, CLARIFY, CODE_REF, DELIB


class VersionFieldTests(unittest.TestCase):
    def test_every_analyzer_declares_a_version(self):
        for a in all_analyzers():
            with self.subTest(analyzer=a.name):
                self.assertIsInstance(a.version, int)
                self.assertGreaterEqual(a.version, 1)

    def test_register_requires_a_version_explicitly(self):
        # No default: an author must make the choice, not inherit a silent one.
        with self.assertRaises(TypeError):
            register("no_version", claims=("tempo",), denominator="turns")(lambda ev: {})

    def test_version_is_carried_into_the_result_dict(self):
        # cli.py merges it in alongside "denominator" — see test_cli_surface.py
        # for the end-to-end JSON assertion; here we just check the contract
        # the CLI relies on: every registered analyzer HAS a version to merge.
        for a in all_analyzers():
            self.assertTrue(hasattr(a, "version"))


class ClassifierHashDisciplineTests(unittest.TestCase):
    """The maintenance-discipline test IDEAS.md asks for: fails when a
    classifier regex (or a threshold an analyzer's semantics depend on)
    changes without a deliberate version bump.

    Each analyzer module keeps its OWN `_..._INPUTS` tuple built from the live
    regex `.pattern` strings / threshold constants, and its OWN pinned
    `_..._HASH` literal. This test does not know what "correct" semantics
    look like — it only checks that the pinned hash still matches what the
    live inputs hash to. A mismatch means: someone edited a classifier or a
    threshold and did not update the pinned hash (and, ideally, the version)
    beside it.
    """

    def test_pinned_hash_matches_live_classifier_inputs_for_every_analyzer(self):
        by_name = {a.name: a for a in all_analyzers()}
        for name, a in by_name.items():
            with self.subTest(analyzer=name):
                live = semantic_hash(*a.semantic_inputs)
                self.assertEqual(
                    live,
                    a.semantic_hash,
                    f"{name}'s semantic_hash no longer matches its live classifier/threshold "
                    f"inputs — a regex or threshold changed. Bump `version` in the @register(...) "
                    f"call, then recompute semantic_hash(*semantic_inputs) and paste the new value "
                    f"in as the pinned semantic_hash (see corpuslens/analyze/__init__.py).",
                )

    def test_composition_mix_pins_the_actual_live_classifier_regexes(self):
        # A hash pinned against the WRONG object (a copy, a stale re-derivation)
        # would pass forever and catch nothing. Assert the module's declared
        # inputs really are today's live `.pattern` strings from the adapter
        # that defines them, not some other text that happens to hash the same.
        self.assertIn(AUTHORED.pattern, composition_mod._COMPOSITION_MIX_INPUTS)
        self.assertIn(CODE_REF.pattern, composition_mod._COMPOSITION_MIX_INPUTS)
        self.assertIn(DELIB.pattern, composition_mod._COMPOSITION_MIX_INPUTS)

    def test_clarification_pull_pins_the_actual_live_clarify_regex(self):
        self.assertIn(CLARIFY.pattern, composition_mod._CLARIFICATION_PULL_INPUTS)

    def test_tempo_pins_its_actual_live_thresholds(self):
        self.assertIn(str(tempo_mod.BURST_S), tempo_mod._TEMPO_INPUTS)
        self.assertIn(str(tempo_mod.RESUMED_S), tempo_mod._TEMPO_INPUTS)

    def test_editing_a_pinned_classifier_source_breaks_the_hash(self):
        # Proves the mechanism actually catches something, rather than always
        # trivially passing: hash the SAME inputs with one character changed
        # and confirm it no longer matches the pinned literal. This is the
        # failure a real regex edit would produce.
        mutated = semantic_hash(
            AUTHORED.pattern + "X", CODE_REF.pattern, DELIB.pattern, "12", "3.0"
        )
        self.assertNotEqual(mutated, composition_mod._COMPOSITION_MIX_HASH)

    def test_semantic_hash_is_order_and_content_sensitive(self):
        self.assertNotEqual(semantic_hash("a", "b"), semantic_hash("b", "a"))
        self.assertNotEqual(semantic_hash("ab", "c"), semantic_hash("a", "bc"))
        self.assertEqual(semantic_hash("a", "b"), semantic_hash("a", "b"))

    def test_thread_span_has_no_classifier_dependency_and_says_so(self):
        # thread_span is pure day-offset arithmetic; nothing to pin. Documented
        # by an empty semantic_inputs tuple rather than a fabricated one.
        span = next(a for a in all_analyzers() if a.name == "thread_span")
        self.assertEqual(span.semantic_inputs, ())


class DiscoveryTests(unittest.TestCase):
    """Guards against a future analyzer being added to a module without ever
    being wired into `_SEMANTIC_INPUTS`/`_SEMANTIC_HASH` at all — silence,
    not a wrong hash, is the harder failure mode to catch."""

    def test_analyzers_known_to_depend_on_claude_code_classifiers_declare_inputs(self):
        depends_on_classifiers = {"composition_mix", "clarification_pull"}
        for a in all_analyzers():
            if a.name in depends_on_classifiers:
                with self.subTest(analyzer=a.name):
                    self.assertTrue(
                        a.semantic_inputs,
                        f"{a.name} depends on a claude-code classifier but declares "
                        f"no semantic_inputs to hash",
                    )


if __name__ == "__main__":
    unittest.main()


class LayeringTests(unittest.TestCase):
    """The analyzer layer must not import an adapter.

    Until 0.2.1 `analyze/composition.py` imported the four classifiers from
    `ingest/claude_code.py` — one adapter, by name — because that is where they
    happened to be written first. Three features added in 0.2.0 all needed the
    classifier set, and all three reached into that same adapter for it. They
    now live in top-level `corpuslens.classifiers`, owned by neither layer.

    This test is the thing that keeps it that way. It fails if any analyzer
    imports from `corpuslens.ingest` again, which is the shape the coupling had
    the first time and the shape it would take the next time.
    """

    def test_no_analyzer_imports_the_ingest_layer(self):
        import pathlib

        analyze_dir = pathlib.Path(__file__).resolve().parent.parent / "corpuslens" / "analyze"
        offenders = []
        for f in sorted(analyze_dir.glob("*.py")):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if "ingest" in stripped:
                    offenders.append(f"{f.name}:{i}: {stripped}")
        self.assertEqual(
            offenders,
            [],
            "analyzers must not import the ingest layer; "
            "shared things belong in corpuslens/classifiers.py",
        )
