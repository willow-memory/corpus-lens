# corpus-lens — idea pile

This repo's numbered idea pile, in the shape willow-reconciler reads: top-level
`N. ` items, optional legend tags, stable numbers. It is the index; the
reasoning behind every item stays in [IDEAS.md](../IDEAS.md), whose sections
each item names. This file is read by:

```sh
reconciler run --repo ./ --doc docs/ideas.md --validate
```

Legend: ✅ shipped · 🟡 partial · (untagged) proposed

**Numbers are permanent join keys.** `reconciler/ids.py` derives
`willow-ideas-<num>` (the fleet-wide prefix; at willow-reconciler 0.6.0 the id
is not qualified by repo) from the number written on the line, so a number is
an identity, not an ordinal. Never renumber; never write a markdown-auto-numbered
list (`1.` repeated) here — retire a number instead and leave the gap.

A legend tag is written only where git history shows the landing, and the
commit is named on the line. An untagged item is proposed, or a recorded
decision not to build; the line says which.

---

## A. Near — small, and the value is clear

1. ✅ **shipped**: `corpuslens diff two runs` — 0.2.0 (385dd78), with per-analyzer semantic versions (6801e74) as the entry required; an absent version is its own status, not a changed classifier (ab90256). IDEAS.md § "`corpuslens diff two runs`".
2. ✅ **shipped**: zero-config first run — bare `corpuslens run` reads each adapter's declared location and names what it found before reading anything (d33138d); the audit finding that it put a resolved home path into the audit sentence is fixed (10f0b37). IDEAS.md § "Zero-config first run".
3. ✅ **shipped**: split the drop count — `doctor` reports structural drops apart from malformed ones (07a7fb5, 0.7.1); BUGS.md, "`doctor`'s drop warning misfired on agentic corpora". IDEAS.md § "Split the drop count".
4. ✅ **shipped**: say which rubric question each analyzer answers, and that two answer none (049a447). IDEAS.md § "Say which rubric question each analyzer answers".
5. 🟡 **partial**: lead with the quickstart — the subcommands and their honesty notes are folded into the README (97b6cab); splitting the wall essay and the reflexivity section into a DESIGN.md has not happened, and the README is longer, not shorter. IDEAS.md § "Lead with the quickstart".
6. ✅ **shipped**: a local labelling mode — `corpuslens label` and `corpuslens score` (52de679, 0.2.0); the sample-size argument stays open as item 30. IDEAS.md § "A local labelling mode".
7. ✅ **shipped**: refuse a corpus the classifiers cannot read — past `SMALL_N` with no code-classifier match, `composition_mix` and `clarification_pull` name both readings and choose neither (56f5d93, 0.2.0). IDEAS.md § "Refuse a corpus the classifiers cannot read".
8. ✅ **shipped**: a share mode for the report — `--share`, composing with `--format` (34bbf9a), with the audit's banding fix (e18f417) and the share-shape guard (1d9ac38). IDEAS.md § "A share mode for the report".
9. ✅ **shipped**: say whose corpus the reference is — the N=1 is labelled the author's own wherever the comparison appears (049a447). IDEAS.md § "Say whose corpus the reference is".

## B. Analyzers worth considering

10. Report the opener-to-follow-up word ratio as a first-class number with its own reading: it is already computed (`opener_median_words` over `followup_median_words`) and separates big-task operators (5.9x, 9.2x) from conversational ones (1.0–1.4x), which `mid_task_share` cannot. IDEAS.md § "`mid_task_share` does not measure what question 1 reads it as".
11. Rewrite GRADING.md question 1's guidance to describe what `mid_task_share` measures, and decide whether the rubric's implied ranking of steering over front-loading survives generative work at all. IDEAS.md § "And the framing carries a value judgment that is wrong for this operator".
12. Correction / redirect rate — how often an operator turn walks back the previous one; the classifier must undercount, since "no, do X instead" has to be told from ordinary elaboration (cf. `agent-retro`). IDEAS.md § "Analyzers worth considering".
13. Convergence / drift / thrash per thread, plus productive-versus-wasted turns (cf. `agent-insights`, which reached `thread_shape`'s concurrency signal independently). IDEAS.md § "Analyzers worth considering".
14. Backtrack detection with severity — intended spec versus actual execution (cf. `clens`). IDEAS.md § "Analyzers worth considering".
15. Turn-length trajectory within a thread — do prompts get shorter (converging) or longer (re-specifying); pure feature data already on the `Event`, no new ingest. IDEAS.md § "Analyzers worth considering".

## C. Adapters

16. A corpus with no clock, handled rather than refused whole: a representable "unknown" `day_offset` that is not zero, an audit sentence that says the corpus has no clock, and `{"error": …}` from `tempo`, `thread_shape` and `thread_span` rather than a computation over a constant — measured against SWE-agent's trajectories, where `steering_density` and `composition_mix` answer questions 1 and 2 without one. IDEAS.md § "A corpus with no clock is refused whole, and two analyzers do not need one".
17. 🟡 **partial**: "operator" was not a person, and nothing noticed — operator-role turns are classified human/agent/unknown and the run derives its subject and stops calling a machine "you" (74bd7dc, 2ba166f, 0.4.0); what stays open is items 18 and 19. IDEAS.md § "The harder finding".
18. The marked-machine path is dead code: it is the authorship classifier's highest-precision signal and no shipped adapter sets it, because every adapter drops a marked record before an `Event` exists (`analyze/authorship_mix.py` passes `marked_machine=False` for that reason). IDEAS.md § "The harder finding", first of three.
19. Grade the authorship classifier on a real corpus through `label` and `score` — nobody knows its error rate; everything rests on one operator's n≈18 per side plus a synthetic falsifier that can break the classifier and never validate it. IDEAS.md § "The harder finding", third of three.
20. A claude.ai web-export adapter — named unbuilt; the export format is stable and documented enough to read. IDEAS.md § "Adapters".
21. ✅ **shipped**: a Forge adapter over the checkpoint ledger (e56f502, 0.5.0), with three analyzers declared unmeasurable by name through a per-adapter registry that `run` refuses and `doctor` lists. IDEAS.md § "Adapters".
22. An agent-fleet adapter — a different instrument with a different subject, not a wider net for this one; the scope question (whose process a fleet's traffic is) comes before any code. IDEAS.md § "Adapters".
23. 🟡 **partial**: more runtimes on the same seam — `gemini-cli` shipped from the writer's source and has never run against a real corpus (9715802, 0.2.0); Codex CLI, opencode and aider are documented refusals with citations, not oversights. IDEAS.md § "Adapters".

## D. Further out, and harder

24. Bootstrap CIs / band-sensitivity on rates — worth doing only alongside a measured estimate of classifier error, or the interval would look rigorous while understating the real uncertainty. IDEAS.md § "Bootstrap CIs / band-sensitivity on rates".
25. A prose renderer — a paragraph a person reads rather than a list, that never says more than the numbers support. IDEAS.md § "A prose renderer".
26. 🟡 **partial**: the guardian-consent model (owner ≠ subject) — the representable half shipped as the vendored consent core and `run --subject … --consent-store …`, fail-closed before any file is opened (88251b5, 0.5.0); the ethics half, who may consent for whom, stays out of scope by decision. IDEAS.md § "The guardian-consent model (owner ≠ subject)".
27. Publish the wall as a reusable mechanism — the Guard extracted as its own small library; designed in DESIGN-guard-extraction.md (399a1fc), sequenced after two or three Near items pull the seam into shape, and not done. IDEAS.md § "Publish the wall as a reusable mechanism".
28. 🟡 **partial**: the leakage demonstration — `timing_fingerprint()` ships as a computation (96c3b25, 0.2.0), with the entropy estimate's sample-size bias corrected (4f767f7); no analyzer registers the `leakage_demonstration` claim and there is deliberately no `corpuslens fingerprint` command until the no-capability-flag question in `cli.py` is decided. IDEAS.md § "The leakage demonstration".

## E. Stretch — capability the tool should have, with no good read yet

29. Population reference points without pooling anyone's corpus — needs a re-identification analysis of the report, not the corpus, at plausible cohort sizes first; the likely honest outcome is a documented refusal or a separate opt-in project. IDEAS.md § "Population reference points without pooling anyone's corpus".
30. Measuring the classifiers' own error, the part `label` does not cover: a sample-size argument, and per-classifier, per-corpus-type error rates published from more than one operator's labels. IDEAS.md § "Measuring the classifiers' own error".
31. Outcome-linked claims — reviewed 2026-09-11 and recommended left alone: a process-to-quality claim changes the shape of what the tool asserts, and every other item gets more valuable without it. Recorded so the next person starts from a decision, not a gap. IDEAS.md § "Outcome-linked claims".
32. ✅ **shipped**: metrics that stay comparable across tool versions — a per-analyzer `version` recorded in every result, `diff` refusing across a change, and the discipline test that fails when a classifier's inputs change without a version bump (6801e74; `tests/test_analyzer_versions.py`). IDEAS.md § "Metrics that stay comparable across tool versions".
33. Process when the work is delegated — a stated model of delegated authorship, probably a new `author_class`, and a decision about which GRADING.md questions still mean anything when the work is nested; measured on one night's corpus (a director and a harness from the same work), not settled. IDEAS.md § "Process when the work is delegated".
34. A lens that stays a lens — the reflexivity effect is disclosed in the README (0dcedf0) but its size is unmeasured, and live feedback stays a refusal unless what the tool is for changes. IDEAS.md § "A lens that stays a lens".
35. Corpora that are not code — the analyzers that would replace `CODE_REF` and `AUTHORED` for another domain, with their own reference points measured from scratch; the refusal half shipped as item 7. IDEAS.md § "Corpora that are not code".

## F. Named and deliberately unbuilt (README, "Status")

36. `distinctive_tokens` and any content-derived token feature — absent until the feature layer has its own PII scrub, because that feature is where names and identities live. README § "Status"; IDEAS.md § "Analyzers worth considering".
37. `turns_to_completion` — on the claim allowlist with no analyzer: these corpora record an abandoned thread and a finished one identically, so the number would be a guess wearing a denominator. README § "Status".

## G. Known bugs, open (BUGS.md)

38. A prompt-to-prompt tempo, human turn to human turn, as an additional field with a `version` bump and a re-based reference point; the headline's wording was corrected to what `delta_prev_s` measures, the measurement itself was not changed. BUGS.md Open, bug 1.
39. Use the compaction boundary in `thread_shape` and `thread_span` — needs one real compacted transcript in the fixtures, anchor quarantined, so the record shape is observed rather than described, then an analyzer `version` bump. BUGS.md Open, bug 2.
40. `changelog_dedup.py` cannot fix a first release's section — fix in forge-play first, then re-sync; the vendored body is hash-pinned to Forge's by `tests/test_vendor_pins.py`, so the re-sync is a recorded act. BUGS.md Open, bug 3.
41. An unclosed known wrapper tag consumes the rest of the turn — a deliberate trade against counting injected context as typed text, listed because it is a way to lose real text and the odds rise as the tag list grows. BUGS.md Open, bug 4.

## H. Tooling and evidence

42. Adopt `Idea-Id` commit trailers (fleet CONVENTION, decision-2026-09-11): this pile as the numbered join target, `.github/workflows/trailers.yml` running `reconciler verify` on every PR, and the convention written into CONTRIBUTING.md.
43. Close the meta-scan's declared blind spot — a helper written as a `TestCase` method that reads a file and hands the text to an `assertIn` (`tests/test_render.py`, `PackagingTests`) is invisible to both halves of `tests/test_scans_fire.py`; the inline half would need to trace reads through same-class calls.
44. The fleet CI floor (fleet plan decision 5): a Linux matrix derived from pyproject's `Programming Language :: Python :: 3.X` classifiers, a Windows job on the floor and ceiling Pythons, ruff pinned to an exact release for `check` and `format --check`, CodeQL over python and actions, and an aggregate `test` gate that fails on any leg whose result is not `success` — skipped and cancelled included — with `tests/test_ci_floor.py` holding each part in place, planted.
