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

from .analyze import SMALL_N  # noqa: F401 — re-exported; tests import it from here too

SCHEMA_VERSION = 1

CAVEAT = ("Numbers are heuristics plus your own eyes: spot-check before you cite. "
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
    "bucket, per-day/month counts, or whether a return was productive). Three of the battery's "
    "seven analyzers (tempo, clarification_pull, signature_plurality) answer none of the ten "
    "numbered questions directly and are reported here as a supporting signal, not a rubric "
    "answer — each section below says "
    "exactly which case it is. Questions 5-8 (can a stored claim be demoted; when a negative "
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
_SHOWN = ("headline", "reading", "vs_coding_population", "error", "grading_question", "reference")


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
    out.append(f"> {RUBRIC_SCOPE_NOTE}")
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
    out.append(f"*{CAVEAT}*")
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
        "caveat": CAVEAT,
    }
    if share:
        doc["share_caveat"] = SHARE_CAVEAT
    return json.dumps(doc, indent=2, default=str, sort_keys=False)


RENDERERS = {"markdown": markdown, "json": json_report}


def available() -> list[str]:
    return sorted(RENDERERS)


def render(fmt: str, results: dict, audit, share: bool = False) -> str:
    if fmt not in RENDERERS:
        raise KeyError(f"no renderer {fmt!r}; available: {available()}")
    return RENDERERS[fmt](results, audit, share=share)
