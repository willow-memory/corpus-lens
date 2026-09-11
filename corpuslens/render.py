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

SCHEMA_VERSION = 1

CAVEAT = ("Numbers are heuristics plus your own eyes: spot-check before you cite. "
          "Reference points are one measured N=1 plus public population aggregates.")


def markdown(results: dict, audit) -> str:
    out = ["# corpuslens report", ""]
    out.append(f"> {audit.sentence()}")
    out.append("")
    for name, res in results.items():
        out.append(f"## {name}")
        out.append("```json")
        out.append(json.dumps(res, indent=2, default=str))
        out.append("```")
        out.append("")
    out.append(f"*{CAVEAT}*")
    return "\n".join(out)


def json_report(results: dict, audit) -> str:
    """The same run as machine-readable JSON. Stable top-level shape:
    {schema_version, audit: {...,"sentence": ...}, results: {...}, caveat}."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "audit": audit.as_dict(),
        "results": results,
        "caveat": CAVEAT,
    }
    return json.dumps(doc, indent=2, default=str, sort_keys=False)


RENDERERS = {"markdown": markdown, "json": json_report}


def available() -> list[str]:
    return sorted(RENDERERS)


def render(fmt: str, results: dict, audit) -> str:
    if fmt not in RENDERERS:
        raise KeyError(f"no renderer {fmt!r}; available: {available()}")
    return RENDERERS[fmt](results, audit)
