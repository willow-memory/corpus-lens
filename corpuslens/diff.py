"""corpuslens diff — compare two `--format json` runs and report the delta
for every shared headline number.

A single reading has no baseline except a stranger's N=1 (see IDEAS.md,
"corpuslens diff two runs"). A diff makes a SECOND reading meaningful — but
only if the two runs are actually the same instrument pointed at the same
kind of corpus. This module draws a line between two kinds of mismatch:

HARD REFUSALS — the whole diff is refused, no numbers emitted at all:
  * different `schema_version` between the two documents. The JSON envelope
    itself may be shaped differently going forward (new/renamed/restructured
    fields); this code was built to read exactly one shape, and guessing that
    a field in a future shape means the same thing as today's would be an
    overclaim about the tool, not about the reader's process. There is
    currently only one shape (`render.SCHEMA_VERSION == 1`), so this refusal
    is presently unreachable in practice — it exists for the day it isn't.
  * different `adapter`. `claude-code` and `cursor` (and `cursor-store`,
    `sqlite`, `postgres`) are different instruments over different kinds of
    corpus, with different classifiers available (cursor has no assistant
    turns at all, so `clarification_pull` cannot even exist on that side).
    A delta between two adapters is not "your process changed" under any
    reading — it is comparing two different measuring devices.  Refusing
    beats annotating here because there is no number on either side that
    would remain meaningful next to a loud warning.

LOUD ANNOTATIONS — the diff still runs, deltas are still computed wherever
they honestly can be, but the comparability problem is named where it cannot
be missed (a `comparability_warnings` list at the top of the document, and a
banner at the top of the markdown rendering):
  * either run's audit shows a `--since-day`/`--until-day` window. Still the
    same tool on the same corpus — but a SUBSET compared against a (possibly
    different) subset, or against the whole corpus. This is a real, nameable
    scope difference a reader may genuinely want (comparing month 1 against
    month 2 of the same corpus is a legitimate diff), so it stays a loud
    warning rather than a refusal — unlike the two conditions above, there is
    no reading under which the numbers on both sides are simply incompatible,
    only one under which they need the caveat attached.
  * a shared analyzer's `analyzer_version` differs between the two runs. This
    is exactly what per-analyzer semantic versions exist to catch (see
    `corpuslens/analyze/__init__.py` and IDEAS.md, "Metrics that stay
    comparable across tool versions"): the classifier or threshold behind
    that ONE number changed, so a delta there would report a software change
    as if it were a process change. It is scoped to the single analyzer that
    disagrees, not the whole diff, because refusing the entire comparison
    over one analyzer's version bump would silently withhold every OTHER
    number that is still honestly comparable — its own kind of overclaim, by
    omission, in the direction of concealing information rather than fabricating it.

A diff is a corpuslens result: whatever it emits, it carries both source
runs' full audit records — including their plain-language sentences — so a
reader of the diff's numbers is never separated from the statement of what
left the wall to produce them (the same rule `render.json_report` holds for a
single run).

No new wall exposure here: `compare()` only recombines fields already public
in two files that each already passed `Guard.scan_egress` when they were
produced (`corpuslens run --format json`); there is no Quarantine object at
this layer to guard because no new Event data is read. If `load_report` is
ever asked to read something that ISN'T a `corpuslens run` JSON document — a
different tool's export, a hand-edited file, garbage — it fails with a clear
message, never a traceback and never a guess.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .render import CAVEAT

# The DIFF DOCUMENT's own shape — distinct from the `schema_version` carried
# inside each of the two input reports, and from each analyzer's `version`.
# Three different questions, three different numbers, on purpose.
DIFF_SCHEMA_VERSION = 1

_NUMERIC_TYPES = (int, float)
_REQUIRED_KEYS = ("schema_version", "audit", "results", "caveat")


class DiffError(Exception):
    """A run file could not be read as a corpuslens report. Always carries a
    plain-language message; the CLI prints it and exits, never a traceback."""


def load_report(path: str) -> dict:
    """Read and minimally validate one `--format json` run. Raises DiffError
    — with a message naming exactly what was wrong — on anything short of a
    well-shaped corpuslens document: an unreadable file, malformed JSON, a
    JSON value that isn't an object, or one missing a field every corpuslens
    JSON report carries."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise DiffError(f"could not read {path}: {e}") from e
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise DiffError(f"{path} is not valid JSON ({e}) — is this a "
                        f"`corpuslens run --format json` output file?") from e
    if not isinstance(doc, dict):
        raise DiffError(f"{path} is not a corpuslens JSON report: expected a JSON object at the "
                        f"top level, got {type(doc).__name__}")
    missing = [k for k in _REQUIRED_KEYS if k not in doc]
    if missing:
        raise DiffError(f"{path} is not a corpuslens JSON report (missing "
                        f"{', '.join(missing)}) — produce it with `corpuslens run "
                        f"--format json`, not a different tool or format")
    if not isinstance(doc["audit"], dict) or "sentence" not in doc["audit"]:
        raise DiffError(f"{path} has a malformed 'audit' field (no audit sentence) — "
                        f"is this really a corpuslens report?")
    if not isinstance(doc["results"], dict):
        raise DiffError(f"{path} has a malformed 'results' field (expected an object)")
    return doc


def _is_number(v) -> bool:
    return isinstance(v, _NUMERIC_TYPES) and not isinstance(v, bool)


def _numeric_fields(res: dict) -> dict:
    """The top-level numeric fields of one analyzer's result that are
    candidates for a delta: excludes `analyzer_version` (compared for
    comparability, never delta'd as if it were a metric) and anything that
    isn't a plain number (headline text, nested reference tables, notes)."""
    return {k: v for k, v in res.items() if k != "analyzer_version" and _is_number(v)}


def _analyzer_diff(name: str, res_a: Optional[dict], res_b: Optional[dict]) -> dict:
    if res_a is None:
        return {"status": "b_only",
                "note": f"'{name}' has a result only in the second report — not diffed."}
    if res_b is None:
        return {"status": "a_only",
                "note": f"'{name}' has a result only in the first report — not diffed."}
    ver_a, ver_b = res_a.get("analyzer_version"), res_b.get("analyzer_version")
    if ver_a is None or ver_b is None:
        # Per-analyzer versions did not exist before they were introduced, so a
        # report older than that carries no version at all. Saying "the
        # classifier changed" here would state something the tool does not know
        # — nothing changed, the field simply was not written. The comparison is
        # still withheld, because absence of a version is absence of evidence
        # that the semantics match, and this project reads absence as denial.
        which = ("Both reports predate" if (ver_a is None and ver_b is None)
                 else ("The first report predates" if ver_a is None
                       else "The second report predates"))
        return {"status": "unversioned", "a_version": ver_a, "b_version": ver_b,
                "note": (f"{which} per-analyzer versioning, so '{name}' carries no version to "
                         f"check. That is not evidence the two runs mean the same thing, and it "
                         f"is not evidence they differ — the tool cannot tell. NOT DIFFED. Re-run "
                         f"the older corpus with this version of corpuslens to get a comparison "
                         f"it can stand behind.")}
    if ver_a != ver_b:
        return {"status": "version_mismatch", "a_version": ver_a, "b_version": ver_b,
                "note": (f"'{name}' ran as analyzer_version {ver_a} in the first report and "
                        f"{ver_b} in the second: the classifier or threshold behind this number "
                        f"changed between the two runs, so a delta here could report a software "
                        f"change as if it were a change in your process. NOT DIFFED. Which "
                        f"direction that change moved the number, and by how much, is not "
                        f"derivable from the two documents — read the changelog between "
                        f"analyzer_version {ver_a} and {ver_b} for what actually changed. See "
                        f"IDEAS.md, \"Metrics that stay comparable across tool versions\".")}
    err_a, err_b = res_a.get("error"), res_b.get("error")
    if err_a or err_b:
        which = "both reports" if (err_a and err_b) else ("the first report" if err_a else
                                                           "the second report")
        return {"status": "not_computable", "a_version": ver_a, "b_version": ver_b,
                "note": f"'{name}' was not computable on {which} ({err_a or err_b}). NOT DIFFED."}
    fields_a, fields_b = _numeric_fields(res_a), _numeric_fields(res_b)
    shared = sorted(set(fields_a) & set(fields_b))
    deltas = {}
    for k in shared:
        va, vb = fields_a[k], fields_b[k]
        delta = vb - va
        if va != 0:
            pct = round(100 * delta / abs(va), 1)
        elif vb == 0:
            pct = 0.0
        else:
            pct = None      # started at zero: a percent change is undefined, not zero
        deltas[k] = {"a": va, "b": vb, "delta": delta, "pct_change": pct}
    entry = {
        "status": "compared",
        "a_version": ver_a, "b_version": ver_b,
        "headline_a": res_a.get("headline"), "headline_b": res_b.get("headline"),
        "deltas": deltas,
    }
    only_a = sorted(set(fields_a) - set(fields_b))
    only_b = sorted(set(fields_b) - set(fields_a))
    if only_a:
        entry["fields_only_in_a"] = only_a
    if only_b:
        entry["fields_only_in_b"] = only_b
    return entry


def _window_clause(audit: dict) -> Optional[str]:
    filters = audit.get("filters") or []
    return "; ".join(filters) if filters else None


def compare(doc_a: dict, doc_b: dict) -> dict:
    """The whole comparison, as data. Never raises for a comparability
    problem between two otherwise-valid reports — those become `refused` /
    `comparability_warnings` in the returned dict so the caller (the CLI's
    renderers) can decide how to present them. `DiffError` is reserved for
    `load_report`: input that could not even be READ as a corpuslens report.
    """
    audit_a, audit_b = doc_a["audit"], doc_b["audit"]
    schema_a, schema_b = doc_a.get("schema_version"), doc_b.get("schema_version")
    adapter_a, adapter_b = audit_a.get("adapter"), audit_b.get("adapter")

    out = {
        "diff_schema_version": DIFF_SCHEMA_VERSION,
        "a": {"schema_version": schema_a, "adapter": adapter_a, "audit": audit_a},
        "b": {"schema_version": schema_b, "adapter": adapter_b, "audit": audit_b},
        "refused": False,
        "refusal_reasons": [],
        "comparability_warnings": [],
        "analyzers": {},
        "caveat": CAVEAT,
    }

    refusals = []
    if schema_a != schema_b:
        refusals.append(
            f"schema_version differs ({schema_a!r} vs {schema_b!r}): the two JSON documents may "
            f"not be shaped the same way — refusing rather than assuming a field in one means "
            f"what the same-named field means in the other.")
    if adapter_a != adapter_b:
        refusals.append(
            f"adapter differs ({adapter_a!r} vs {adapter_b!r}): these are two different "
            f"instruments run over two different kinds of corpus, not one instrument run twice — "
            f"a delta between them would not be a trend in your process.")
    if refusals:
        out["refused"] = True
        out["refusal_reasons"] = refusals
        return out

    win_a, win_b = _window_clause(audit_a), _window_clause(audit_b)
    if win_a or win_b:
        pieces = []
        if win_a:
            pieces.append(f"the first report was filtered ({win_a})")
        if win_b:
            pieces.append(f"the second report was filtered ({win_b})")
        out["comparability_warnings"].append(
            "SUBSET COMPARISON: " + "; ".join(pieces) + ". These are subset numbers on at least "
            "one side, not whole-corpus numbers — a delta below may reflect the window, not a "
            "change in your process.")

    results_a, results_b = doc_a["results"], doc_b["results"]
    names = sorted(set(results_a) | set(results_b))
    version_mismatches = []
    unversioned = []
    for name in names:
        entry = _analyzer_diff(name, results_a.get(name), results_b.get(name))
        out["analyzers"][name] = entry
        if entry["status"] == "version_mismatch":
            version_mismatches.append(name)
        elif entry["status"] == "unversioned":
            unversioned.append(name)
    if version_mismatches:
        out["comparability_warnings"].append(
            "ANALYZER VERSION MISMATCH for " + ", ".join(version_mismatches) + ": not diffed "
            "(see each analyzer's own note below). Every other shared analyzer ran the same "
            "version on both sides and IS diffed normally.")
    if unversioned:
        # Two reports that BOTH predate versioning used to compare as equal in
        # silence — the most misleading outcome available, because the reader
        # saw a clean diff and no hint that nothing had been checked.
        out["comparability_warnings"].append(
            "OLDER RUN PREDATES VERSIONING for " + ", ".join(unversioned) + ": not diffed. "
            "These results carry no analyzer_version, which happens when a report was produced "
            "before per-analyzer versions existed. Nothing here says the analyzers changed — it "
            "says the tool has no way to check, which is not the same thing and is not treated "
            "as the same thing.")
    return out


def render_json(d: dict) -> str:
    return json.dumps(d, indent=2, default=str, sort_keys=False)


def render_markdown(d: dict) -> str:
    out = ["# corpuslens diff", ""]
    out += ["## Report A", "", f"> {d['a']['audit']['sentence']}", ""]
    out += ["## Report B", "", f"> {d['b']['audit']['sentence']}", ""]

    if d["refused"]:
        out += ["## REFUSED — these two runs are not comparable", ""]
        for r in d["refusal_reasons"]:
            out.append(f"- {r}")
        out += ["", "*No deltas were computed. Diff two runs that share an adapter and a "
               "schema_version, or accept that this comparison cannot be made honestly.*"]
        return "\n".join(out)

    if d["comparability_warnings"]:
        out += ["## ⚠ COMPARABILITY WARNINGS ⚠", ""]
        for w in d["comparability_warnings"]:
            out.append(f"- **{w}**")
        out.append("")

    out += ["## Deltas", ""]
    for name, entry in d["analyzers"].items():
        out.append(f"### {name}")
        status = entry["status"]
        if status in ("a_only", "b_only", "not_computable", "version_mismatch",
                      "unversioned"):
            out += [f"*{entry['note']}*", ""]
            continue
        if entry.get("headline_a") or entry.get("headline_b"):
            out.append(f"- A: {entry.get('headline_a') or '(no headline — not computable)'}")
            out.append(f"- B: {entry.get('headline_b') or '(no headline — not computable)'}")
        if not entry["deltas"]:
            out.append("*No shared numeric fields to diff.*")
        for k, v in entry["deltas"].items():
            pct = f" ({v['pct_change']:+.1f}%)" if v["pct_change"] is not None else " (from zero)"
            out.append(f"- **{k}**: {v['a']!r} → {v['b']!r} — delta {v['delta']:+g}{pct}")
        out.append("")
    out.append(f"*{d['caveat']}*")
    return "\n".join(out)


RENDERERS = {"markdown": render_markdown, "json": render_json}
