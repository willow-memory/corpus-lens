"""Rendering: the report plus the audit sentence, always together — a result
without its audit record is not a corpuslens result.

Two renderers, one rule. `markdown` is for reading; `json_report` is for
machines (diffing two runs, tracking a number across months, piping into
something else). The JSON form carries the SAME audit record as a structured
object *and* the same plain-language sentence — a consumer that wants only the
numbers still cannot get them without the sentence that says what left the
wall. Both outputs go through `Guard.scan_egress` at the CLI's output door.
"""
from __future__ import annotations

import json
import re

from .analyze import SMALL_N  # noqa: F401 — re-exported; tests import it from here too
from .subject import SUBJECT_HUMAN

SCHEMA_VERSION = 1

CAVEAT = ("Numbers are heuristics plus your own eyes: spot-check before citing them. "
          "Reference points are one measured N=1 plus public population aggregates.")

# Shown once, right after the audit sentence, before any finding — so a reader
# meets the rubric's scope before a single number. This note must never be
# stronger than the per-section grading_question declarations under it (a
# review caught an earlier draft claiming "the first four questions" when the
# real mapping is two full, two partial, and two analyzers answering none) —
# see IDEAS.md, "Say which rubric question each analyzer answers".
RUBRIC_SCOPE_NOTE = (
    "This report's battery fully answers two of GRADING.md's ten questions — question 1 (where "
    "your intent arrives) and question 2 (who writes the code) — and partly answers two more: "
    "question 3 (your deliberation share, but not whether those prompts pull longer, more "
    "structured responses) and question 4 (resumption gaps and thread span, but not a 30-day "
    "bucket, per-day/month counts, or whether a return was productive). {unmapped_clause} "
    "Questions 5-8 (can a stored claim be demoted; when a negative "
    "result was last recorded; whether an agent can grant itself anything; whether checks fail "
    "closed) and questions 9-10 (whether your timestamps are a fingerprint; who carries the "
    "continuity across a session gap) are not corpus-measurable from session logs at all — "
    "GRADING.md gives each of those its own manual test, not a number this tool computes."
)

# Reference dicts mix two different kinds of comparison point: a named public
# population aggregate (WildChat, OASST — or a benchmark construction fact
# like SWE-bench/tau-bench) and the author's own corpus, one person. A key is
# treated as the population kind only if it names one of these; everything
# else in a `reference` dict is the N=1 corpus, whatever its key is spelled
# (`measured_director`, `measured_director_n1`, `measured_cli`,
# `measured_cursor_note` all appear across the analyzers) — see IDEAS.md,
# "Say whose corpus the reference is".
_POPULATION_MARKERS = ("wildchat", "oasst", "swe_bench", "tau_bench")


def _is_population_reference(key: str) -> bool:
    k = key.lower()
    return any(m in k for m in _POPULATION_MARKERS)


def _fmt_reference_value(v) -> str:
    return json.dumps(v) if isinstance(v, (dict, list)) else str(v)


# ── the subject lens: pronouns and reference points follow the SUBJECT ──────
#
# Every analyzer's `headline`/`reading`/`vs_coding_population` prose is
# written second-person ("your prompt turns"), and every `reference` dict
# compares the reader to a HUMAN corpus (the measured N=1 director, WildChat,
# OASST). Both are fine — better than fine, the point of the tool — for the
# common case this project was built around: a human running corpuslens on
# their own logs. They are an overclaim the moment `audit.subject` (see
# corpuslens/subject.py) is anything other than `"human"`: pointed at a
# SWE-agent trajectory, "88.6% of your prompt turns arrive mid-task" is a true
# statement about turns and a false statement about a person, because there is
# no person in that corpus.
#
# `_apply_subject_lens` is the ONE seam both changes go through, applied once
# in `render()` below to a COPY of `results` before either renderer sees it —
# deliberately not a hand-edit of every analyzer's f-string in steering.py /
# composition.py / tempo.py, so a future analyzer's headline is covered by
# construction rather than needing its own opt-in. It is a no-op whenever
# `audit.subject` is `None` (no subject was ever inferred — every direct
# construction of a report outside the real `cli.run()` pipeline, including
# most of this project's own tests) or `"human"` (the run's own authorship
# classifier believes a human wrote these turns, so the existing wording
# already says the true thing).
_PRONOUN_SUBSTITUTIONS = (
    # Longest / most specific casing first so a later, shorter pattern never
    # re-matches text a prior substitution already produced.
    (re.compile(r"\bYOUR\b"), "THE OPERATOR ROLE'S"),
    (re.compile(r"\bYour\b"), "The operator role's"),
    (re.compile(r"\byour\b"), "the operator role's"),
    (re.compile(r"\bYOU\b"), "THE OPERATOR ROLE"),
    (re.compile(r"\bYou\b"), "The operator role"),
    (re.compile(r"\byou\b"), "the operator role"),
)

# Fields depersonalized. Free-text prose only — `_SHOWN` names the same set of
# fields as the ones this renderer treats as sentences rather than numbers.
_PRONOUN_FIELDS = ("headline", "reading", "vs_coding_population")


def _depersonalize(text: str) -> str:
    """Swap second-person pronouns for the neutral, already-defined term this
    project uses for the role in question (`model.AuthorClass.OPERATOR`) —
    never a guess at WHICH non-human author it was, since inventing that
    would be a second overclaim stacked on the first.

    KNOWN, DISCLOSED ROUGH EDGE: this is a plain word substitution, not a
    parser — it does not reconjugate the verb that follows a bare `you` used
    as a grammatical subject with a present-tense verb ("you steer in
    volleys" becomes "the operator role steer in volleys", not "...steers...").
    Every occurrence of `your`/`You ELIDED-PAST-TENSE-VERB` in this codebase
    today is possessive or past-tense, where English does not conjugate for
    person/number, so those read correctly; the few present-tense `reading`
    sentences that do not (composition_mix's "you bring/direct/summon...",
    tempo's "you steer/leave...", thread_span's "you keep... and return...")
    read as mildly ungrammatical rather than wrong. A stdlib-only tool has no
    parser to fix that generally, and a hand-maintained phrase table would
    silently go stale the moment a `reading` string is edited without a
    matching table entry — so the trade this module makes on purpose is
    correctness of REFERENT over polish of PROSE. See NOTES-subject.md.
    """
    for pattern, replacement in _PRONOUN_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text


_REFERENCE_WITHHELD_NOTE = (
    "Reference withheld: this run's subject is inferred as '{subject}' ({reason}). Every "
    "reference point this battery has — the measured N=1 human director, and the WildChat/OASST "
    "population aggregates — is itself a human reference point; comparing a non-human (or "
    "not-confidently-human) subject against one would be a category error this tool declines to "
    "make silently. No agent reference point is substituted, because none has been measured — "
    "'no comparable reference exists for this subject' is itself the finding here, not a gap to "
    "paper over."
)


def _lens_active(audit) -> bool:
    """True iff this run inferred a subject other than `"human"` — the one
    condition that triggers every change in this section (pronouns dropped
    from analyzer prose AND from the two report-wide constants below, and
    cross-subject reference points withheld). `None` (no subject was ever
    inferred — every direct renderer call this project's own tests make)
    counts as inactive, same as `"human"` — nothing to correct without an
    inferred subject to correct it towards."""
    subject = getattr(audit, "subject", None)
    return subject is not None and subject != SUBJECT_HUMAN


def _second_person_off(audit) -> bool:
    """True iff the report must not say "you"/"your": either the inferred
    subject is not human (`_lens_active`), OR the operator named a subject
    who is not themselves (`audit.subject_consent` is set — see
    corpuslens/subject_consent.py). In the second case the operator role may
    well be a human, so the human reference points still apply and are NOT
    withheld; only the pronouns go, because "your prompts" would be
    addressing the reader about someone else's corpus."""
    return _lens_active(audit) or bool(getattr(audit, "subject_consent", None))


def _apply_subject_lens(results: dict, audit) -> dict:
    """Return a COPY of `results` with pronouns depersonalized and
    cross-subject `reference` blocks withheld, when — and only when —
    `audit.subject` names a subject other than `"human"`. `results` itself is
    never mutated: callers (including `render()` below) can hand this the
    same dict a caller still holds elsewhere.
    """
    if not _second_person_off(audit):
        return results
    withhold = _lens_active(audit)
    subject = audit.subject
    reason = getattr(audit, "subject_reason", None) or "no reason recorded"
    out = {}
    for name, res in results.items():
        r = dict(res)
        for field in _PRONOUN_FIELDS:
            v = r.get(field)
            if isinstance(v, str):
                r[field] = _depersonalize(v)
        if withhold and isinstance(r.get("reference"), dict) and r["reference"]:
            del r["reference"]
            r["reference_withheld"] = _REFERENCE_WITHHELD_NOTE.format(subject=subject, reason=reason)
        out[name] = r
    return out

# Shown only when `share=True` — see corpuslens/share.py for what "coarsened"
# means here and, just as load-bearing, what it does NOT mean. This sentence
# travels with the coarsened numbers wherever they go, same principle as the
# audit sentence: a share output without the disclosure of what it is is not
# a corpuslens result either.
SHARE_CAVEAT = (
    "SHARE MODE: this output is COARSENED, not anonymized and not "
    "de-identified — whether a coarsened report can still re-identify its "
    "owner is an open question this tool has not measured (see IDEAS.md, "
    "\"Population reference points without pooling anyone's corpus\"). "
    "Every denominator's n is rounded to a wide band, never an exact count, "
    "and shapes — tempo quantiles, thread counts, day spans, concurrency "
    "figures, active-day counts — are omitted entirely, not just rounded. "
    "This is not a determination that what remains is safe to publish."
)



# Rendered above the numbers block verbatim, so they are omitted from it rather
# than printed twice. Only ever strings already shown — no number is dropped.
_SHOWN = ("headline", "reading", "vs_coding_population", "error", "grading_question", "reference",
          "reference_withheld")



def _unmapped_clause() -> str:
    """The 'N of M analyzers answer none of the ten questions' clause, computed.

    It was hardcoded, and two analyzers added in parallel each updated it for
    their own addition without knowing about the other — so the shipped string
    said three of seven when eight were registered and four answered nothing.
    A false count in user-visible output is the kind of thing this project
    treats as a bug, and the durable fix is to stop writing the number down.
    """
    from .analyze import all_analyzers
    every = all_analyzers()
    unmapped = [a.name for a in every
                if "none of" in (getattr(a, "grading_question", "") or "")]
    if not unmapped:
        return (f"Every one of the battery's {len(every)} analyzers maps onto at least part of "
                "one of the ten numbered questions.")
    names = ", ".join(sorted(unmapped))
    verb = "answers" if len(unmapped) == 1 else "answer"
    noun = "analyzer" if len(unmapped) == 1 else "analyzers"
    return (f"{len(unmapped)} of the battery's {len(every)} {noun} ({names}) {verb} none of the "
            "ten numbered questions directly and are reported here as a supporting signal, not a "
            "rubric answer — each section below says exactly which case it is.")


def _section(name: str, res: dict) -> list:
    out = [f"## {name}", ""]
    if "error" in res:
        # An analyzer that could not compute says why, in words. An empty
        # section would read as a zero, and a zero is a claim.
        out += [f"**Not computable on this corpus.** {res['error']}", ""]
        if res.get("denominator"):
            out += [f"Denominator would be: {res['denominator']}.", ""]
        if res.get("grading_question"):
            out += [f"GRADING.md: {res['grading_question']}.", ""]
        return out
    headline = res.get("headline")
    if headline:
        out += [f"**{headline}**", ""]
    if res.get("grading_question"):
        out += [f"*GRADING.md: {res['grading_question']}.*", ""]
    bits = []
    if res.get("denominator"):
        bits.append(f"Out of {res['denominator']}")
    n = res.get("n")
    if isinstance(n, int):
        bits.append(f"n = {n}")
    if bits:
        out += ["; ".join(bits) + ".", ""]
    if isinstance(n, int) and 0 < n < SMALL_N:
        out += [f"*Small sample (n = {n}): read the direction, not the decimal.*", ""]
    if res.get("vs_coding_population"):
        out += [f"Against the reference: {res['vs_coding_population']}.", ""]
    if res.get("reading"):
        out += [f"> {res['reading']}", ""]
    ref = res.get("reference")
    if isinstance(ref, dict) and ref:
        out.append("Reference:")
        n1_seen = False
        for k, v in ref.items():
            val = _fmt_reference_value(v)
            if _is_population_reference(k):
                out.append(f"- `{k}`: {val}")
            else:
                out.append(f"- `{k}`: {val} — the author's own corpus (N=1); a gap from this "
                           "reference is a gap from one person, not a population.")
                n1_seen = True
        out.append("")
        if n1_seen:
            out += [("*Until someone runs `corpuslens label` and `corpuslens score` on this "
                     "corpus, there is no way to know how much of that N=1 gap is the operator "
                     "and how much is the classifier's own error.*"), ""]
    elif res.get("reference_withheld"):
        out += [f"*{res['reference_withheld']}*", ""]
    numbers = {k: v for k, v in res.items() if k not in _SHOWN}
    if numbers:
        out += ["```json", json.dumps(numbers, indent=2, default=str), "```", ""]
    return out


def markdown(results: dict, audit, share: bool = False) -> str:
    """The report as something to read: the audit sentence, then every
    analyzer's finding in one list, then each with its denominator, its
    direction guidance and its numbers.

    The findings list is the point. A reader who stops after it has the run;
    a reader who continues gets the denominator behind every sentence and the
    full numbers under that. Nothing is summarized away — the prose above a
    section and the JSON in it come from the same result dict.

    `share=True` renders `results` as given — the CALLER coarsens (see
    `corpuslens/share.py`) — and additionally prepends `SHARE_CAVEAT` so the
    coarsening is disclosed in the same place the audit sentence is."""
    out = ["# corpuslens report", ""]
    if share:
        out.append(f"> {SHARE_CAVEAT}")
        out.append("")
    out.append(f"> {audit.sentence()}")
    out.append("")
    # RUBRIC_SCOPE_NOTE is a fixed, report-wide string (not one of the
    # per-analyzer fields `_apply_subject_lens` already rewrote in `results`
    # above) that ALSO says "your" three times — same seam, same reason.
    note = RUBRIC_SCOPE_NOTE.format(unmapped_clause=_unmapped_clause())
    scope_note = _depersonalize(note) if _second_person_off(audit) else note
    out.append(f"> {scope_note}")
    out.append("")
    findings = [(name, res.get("headline")) for name, res in results.items()]
    if findings:
        # Rendered whenever anything ran — including a run where EVERY analyzer
        # came back not-computable. That run is a finding about the corpus, and
        # dropping the list would have made it look like nothing happened.
        out += ["## What this run found", ""]
        for name, headline in findings:
            if headline:
                out.append(f"- **{name}** — {headline}")
            else:
                err = results[name].get("error")
                out.append(f"- **{name}** — not computable on this corpus."
                           + (f" {err}" if err else ""))
        out.append("")
    for name, res in results.items():
        out += _section(name, res)
    caveat = _depersonalize(CAVEAT) if _second_person_off(audit) else CAVEAT
    out.append(f"*{caveat}*")
    return "\n".join(out)


def json_report(results: dict, audit, share: bool = False) -> str:
    """The same run as machine-readable JSON. Stable top-level shape:
    {schema_version, audit: {...,"sentence": ...}, results: {...}, caveat}.

    `share=True` adds a top-level `share_caveat` string (SHARE_CAVEAT) rather
    than changing `results`'s shape — a machine consuming `--format json
    --share` still gets a document shaped exactly like an unshared one, plus
    one more field naming what left the wall differently this time."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "audit": audit.as_dict(),
        "results": results,
        "caveat": _depersonalize(CAVEAT) if _second_person_off(audit) else CAVEAT,
    }
    if share:
        doc["share_caveat"] = SHARE_CAVEAT
    return json.dumps(doc, indent=2, default=str, sort_keys=False)


RENDERERS = {"markdown": markdown, "json": json_report}


def available() -> list[str]:
    return sorted(RENDERERS)


def render(fmt: str, results: dict, audit, share: bool = False) -> str:
    """The one call site both formats go through from `cli.py` — which is
    also why `_apply_subject_lens` lives here rather than inside `markdown()`
    or `json_report()` individually: a caller that reaches either renderer
    directly (this project's own tests do, extensively, with a bare
    `AuditRecord()` whose `subject` is `None`) gets the ORIGINAL wording,
    unchanged, which is correct — the lens has nothing to correct without an
    inferred subject to correct it towards."""
    if fmt not in RENDERERS:
        raise KeyError(f"no renderer {fmt!r}; available: {available()}")
    results = _apply_subject_lens(results, audit)
    return RENDERERS[fmt](results, audit, share=share)
