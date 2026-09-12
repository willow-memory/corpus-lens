"""corpuslens.classifiers — the four regex classifiers, and the features they set.

Lives at the TOP LEVEL, owned by neither layer, because both need it and
neither should reach into the other for it. Ingest runs these over a turn's
text once, at the boundary, and puts only the resulting booleans on an `Event`;
analysis reasons about those booleans and, for its semantic-version hashes,
about the patterns' text. Until 0.2.0 all of this lived in
`ingest/claude_code.py`, so every other adapter and then `analyze/composition.py`
imported one adapter by name to get it — `_rows.py` (which backs both database
adapters), `cursor.py`, `cursor_store.py`, `label.py` and the analyzers. That
was never an adapter's property; it just happened to be written there first.

WHAT THESE ARE, STATED PLAINLY. Regex heuristics with known false-positive and
false-negative modes, weakest on a mixed personal-plus-coding corpus. The rule
from CONTRIBUTING.md is that they must be wrong in the UNDER-counting
direction: a false negative on real code is acceptable, a false positive on
ordinary prose that inflates "you write code" is not.

They are also ENGLISH-AND-PYTHON SHAPED, which is a narrower limit than
"heuristic" suggests. `CODE_REF` knows nine file extensions and Python's own
traceback format; `AUTHORED` knows a handful of languages' block syntax;
`DELIB` and `CLARIFY` are lists of English phrases. A coding corpus in an
unlisted language, or a conversation in another language, scores identically to
one with no code and no deliberation in it. `analyze/composition.py` refuses
rather than reporting that zero once the sample is big enough for "detected
nothing" to mean something.

CHANGING ONE IS A SEMANTIC CHANGE. Every headline rate downstream moves when a
pattern moves. `CLASSIFIER_SET_VERSION` below tags a label store so
`corpuslens score` refuses to grade across a definition change, and
`tests/test_analyzer_versions.py` pins each pattern's text to a hash so an edit
fails the suite until its analyzer's `version` is bumped deliberately.
STILL COUPLED, NOTED RATHER THAN FIXED HERE: `cursor.py` and `gemini_cli.py`
import `_iter_lines`/`_parse_ts` from `claude_code.py`. That is one adapter
reaching into another for JSONL and timestamp helpers — the same shape of
accident as the classifiers, one layer down and far less harmful, since it
crosses no layer boundary. Worth a shared `ingest/_jsonl.py` the next time
someone is in there; not worth the churn on its own.
"""

from __future__ import annotations

import hashlib
import re

# CODE_REF: require CODE-ADJACENT context, not bare English words. Every
# alternative needs a code shape (a call, a dotted call, a fence, a source
# file, a traceback frame, a CamelCase Error/Exception, a real def/import).
# Case-sensitive on the keyword/Error branches so prose "exception"/"error"
# does not match. English-and-Python shaped, disclosed: the source-file
# branch knows NINE extensions and no others (py/js/ts/rs/go/rb/java/sql/sh —
# count them off this line, and if a doc elsewhere says a different number,
# this list is the truth and the doc is the bug), and the traceback branch is
# Python's own "Traceback (most recent call last)" / "line N, in" — a real
# code corpus in an unlisted language or file type scores identically to one
# with no code in it at all.
CODE_REF = re.compile(
    # Call detection matches the reference study's methodology (the READ regex in
    # operator_reading_analysis): an EMPTY-parens call foo() or a dotted method
    # call obj.method( — NOT bare word(word). Bare word(arg) fires on prose asides
    # ("change(s)", "see you(soon)", "kind of(ish)") and inflated code_ref_pct to
    # 100% on a code-free corpus; it is also broader than the reference the number
    # is compared against. Empty/dotted calls do not occur in ordinary prose.
    r"\b[A-Za-z_]\w*\(\s*\)"  # empty call: foo()
    r"|\b[A-Za-z_]\w*\.[A-Za-z_]\w*\("  # method call: obj.method(
    r"|`[^`]+`|```"  # inline / fenced code
    r"|\b\w+\.(py|js|ts|rs|go|rb|java|sql|sh)\b"  # source file
    r"|Traceback \(most recent call last\)"
    r"|\bline\s+\d+,\s+in\b"  # python traceback frame
    r"|\b\w+(Error|Exception)\b"  # ValueError, KeyError (needs prefix)
    r"|\breturn\s+\w+\("  # return a call
    r"|\b(def|class|async def)\s+\w+\s*\("  # def/class with a param list
    r"|\bfrom\s+[\w.]+\s+import\b"  # from x import y
    r"|\bimport\s+[a-z]\w*\.\w",  # import a.b (dotted module)
)
# AUTHORED: pasted code. Every branch requires a CODE SHAPE, not a bare keyword
# — prose openers like "let me know", "static electricity", "var was short for"
# must not count (they inflated authored_code_pct to 40% on a pure-prose corpus
# in review). No generic `x = ...` branch: "Budget = 500", "Plan = [buy milk]",
# "Verdict = (guilty)" are prose; isolated assignments are weak evidence and
# under-counting beats over-claiming "you write code". Case-sensitive.
# English-and-Python shaped, disclosed: the branches below cover Python, JS/TS,
# Java/C#, Go/Rust (func/fn), shell and SQL block syntax — a handful of
# languages, not "code" in general. Real pasted code in a language with none
# of these shapes (or a Python-family dialect whose block syntax differs)
# scores identically to no pasted code at all.
AUTHORED = re.compile(
    r"```"
    r"|^\s*(def|class|async\s+def)\s+\w+\s*\("  # def foo( / class Bar(
    r"|^\s*for\s+\w+\s+in\s+[^\n]*:\s*$"  # for x in ...:
    r"|^\s*(while|if|elif)\b[^\n]*[<>=!(][^\n]*:\s*$"  # while/if with an operator/paren, ending ':'
    r"|^\s*(try|except|finally|else)\s*:\s*$"  # bare block keyword line
    r"|^\s*(public|private|protected|static)(\s+(public|private|protected|static|final|abstract|synchronized))*\s+[\w<>\[\].]+\s+\w+\s*[({=;]"  # java/c# decl (1+ modifiers)
    r"|^\s*(func|fn)\s+\w+\s*\("  # func name(
    r"|^\s*(const|let|var)\s+\w+\s*[:=]"  # const/let/var x = | x:
    # imports anchored to a code shape: a bare module path (optionally `as x`) to
    # end of line, or a full `from x import y` list — so prose "import export
    # business is booming" / "import duty" do NOT match
    r"|^\s*import\s+[\w.]+(\s+as\s+\w+)?\s*$"
    r"|^\s*from\s+[\w.]+\s+import\s+(\*|[\w.]+(\s*,\s*[\w.]+)*)\s*$"
    r"|^\s*[A-Za-z_]\w*\([^)]*\)\s*$"  # a line that is just a call: print(x)
    r"|^\s*#!\s*/|^\s*export\s+\w+="  # shell: shebang / export VAR=
    r"|\|\s*(grep|awk|sed|sort|uniq|head|tail|xargs|wc|jq)\b"  # shell pipe chain
    r"|\b(SELECT|INSERT|UPDATE|DELETE)\b[^\n]*\b(FROM|INTO|SET|WHERE|VALUES)\b"
    r"|console\.log\(|println!\(|System\.out\.",
    re.M,
)
# DELIB and CLARIFY are both lists of ENGLISH phrases — same disclosed limit as
# CODE_REF/AUTHORED's nine file extensions and handful of languages' block
# syntax, just for prose rather than code. A corpus conducted in another
# language matches neither, and looks identical to a corpus where the
# operator never deliberated / the machine never asked a clarifying question.
# Undercounting, not a bug — but it is why `composition_mix` and
# `clarification_pull` refuse rather than report 0.0% once the sample is
# large enough that "detected nothing" would otherwise read as a finding (see
# `analyze/composition.py`).
DELIB = re.compile(
    r"\btalk (to me )?about\b|let'?s (talk|discuss|explore)|\bdiscuss\b|pros?\s*(and|/|\-)\s*cons?"
    r"|trade.?offs?|think (through|about)\b|what do you think"
    r"|\byour thoughts\b|\bany thoughts\b|thoughts on\b|thoughts\?"
    r"|help me (think|understand|decide|figure|weigh)|walk me through"
    r"|weigh (the |our |my )?options\b|what (are|were) (the |my |our )?options|\b(the|my|our) options\b"
    r"|brainstorm|i'?m (thinking|wondering|considering)|convince me|push back",
    re.I,
)
CLARIFY = re.compile(
    r"do you (mean|want)|would you like|should i\b|which (one|of|do|would|approach)"
    r"|to clarify|can you confirm|just to confirm|one question|quick question",
    re.I,
)

#: Version of the four regex classifiers directly above (CODE_REF, AUTHORED,
#: DELIB, CLARIFY) as a set. `corpuslens label` records this in every label
#: store it writes; `corpuslens score` refuses to grade a store recorded
#: against a different version rather than silently comparing across a regex
#: change (IDEAS.md, "A local labelling mode"). Bump this any time any one of
#: the four patterns above changes — a label is a judgment about what a
#: SPECIFIC version of a classifier got right, and it stops being a true
#: judgment about a different version.
CLASSIFIER_SET_VERSION = "regex-classifiers/1"


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8", "replace")).hexdigest()[:16]


def _features(text: str, stripped: bool) -> dict:
    return {
        "word_count": len(text.split()),
        "char_count": len(text),
        "code_fenced": text.count("```") >= 2,
        "code_authored": bool(AUTHORED.search(text)),
        "code_ref": bool(CODE_REF.search(text)),
        "delib": bool(DELIB.search(text)),
        "question": "?" in text,
        "clarify": bool(CLARIFY.search(text)),
        "injected_stripped": stripped,
    }
