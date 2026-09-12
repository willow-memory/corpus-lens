"""Closed-vocabulary failure reporting for foreign processes and libraries.

THE LEAK THIS CLOSES (found by probing, not by reading). The postgres adapter
shelled out to `psql` and raised `ValueError(f"psql error: {proc.stderr}")`,
which `cli.py` then printed as an `error:` line. `psql` echoes the whole
connection URI back on a URI parse error, so:

    corpuslens run --adapter postgres "postgres://seanuser:hunter2@[bad/corpus"
    error: psql error: psql: error: end of string reached when looking for
    matching "]" in IPv6 host address in URI: "postgres://seanuser:hunter2@[bad/corpus"

— the operator's database **password**, in plaintext, on stderr, into shell
scrollback and CI logs. Nothing in this repo authored that text, and nothing
watched it: `Guard.scan_egress` (both phases) guards the *report*, and an
error is not a report. **Errors are an egress path too.**

THE RULE, borrowed from redential-cli's `src/errors.ts` / `src/http-client.ts`
(Apache-2.0, same license), whose `NetworkError` contract is:

    Message is built from the request's host, HTTP status, and a closed
    failure-class phrase from `error.code` — never headers, body, or
    `error.message` — so it can never echo a bearer token or bundle content.

Applied here: a failure in foreign code is reported as **one phrase from the
closed list below, and nothing else**. Reading the foreign text to classify it
is fine; *interpolating* it is what leaks. So `classify()` takes the text and
returns only a member of `FAILURE_CLASSES` — there is no code path by which
its input reaches its output.

WHY A CLOSED LIST AND NOT A REDACTOR. A redactor has to enumerate what is
secret, and is wrong the first time a foreign tool prints a secret in a shape
nobody predicted — the same open-ended bet that made the literal egress scan
miss three never-quarantined values. A closed vocabulary inverts it: the only
strings that can be emitted are the ones written here, so an unanticipated
secret cannot escape by default. An unrecognized failure degrades to
`UNKNOWN`, which says less than the operator might want and cannot leak.

WHAT THIS COSTS, STATED PLAINLY. Debuggability. "authentication failed" is
genuinely less useful than psql's own sentence, and an operator debugging a
connection will sometimes have to reproduce the failure with `psql` directly.
That is the intended trade and it must not be quietly undone by adding "...
(detail: {stderr})" to a message here later.
"""

from __future__ import annotations

#: The closed vocabulary. A reporter may emit these strings and no others.
FAILURE_CLASSES: frozenset[str] = frozenset(
    {
        "could not resolve the host name",
        "connection refused",
        "connection timed out",
        "authentication failed",
        "the named database does not exist",
        "permission denied by the server",
        "TLS/SSL negotiation failed",
        "the connection string is malformed",
        "the query was rejected",
        "the file is not a readable database",
        "the database is locked",
        "the database file could not be opened",
        "the client binary is missing",
        "the operation timed out",
        "unknown failure",
    }
)

UNKNOWN = "unknown failure"

#: (marker, class). Markers are matched case-insensitively against the foreign
#: text; the FIRST match wins, so more specific markers come first. Markers are
#: only ever compared against, never emitted.
_MARKERS: tuple[tuple[str, str], ...] = (
    # Malformed connection strings first: psql echoes the URI verbatim in these,
    # which is the exact case that leaked a password.
    ("in uri", "the connection string is malformed"),
    ("invalid uri", "the connection string is malformed"),
    ("invalid connection option", "the connection string is malformed"),
    ('missing "=" after', "the connection string is malformed"),
    ("could not translate host name", "could not resolve the host name"),
    ("name or service not known", "could not resolve the host name"),
    ("no address associated with hostname", "could not resolve the host name"),
    ("connection refused", "connection refused"),
    ("no route to host", "connection refused"),
    ("timeout expired", "connection timed out"),
    ("connection timed out", "connection timed out"),
    ("password authentication failed", "authentication failed"),
    ("authentication failed", "authentication failed"),
    ("no password supplied", "authentication failed"),
    ('role "', "authentication failed"),
    ("file is not a database", "the file is not a readable database"),
    ("encrypted or is not a database", "the file is not a readable database"),
    ("database disk image is malformed", "the file is not a readable database"),
    ("database is locked", "the database is locked"),
    ("unable to open database file", "the database file could not be opened"),
    ("no such table", "the query was rejected"),
    ("no such column", "the query was rejected"),
    # Postgres phrases a bad table/column reference as `relation "x" does not
    # exist` / `column "x" does not exist` — it reuses the SAME "does not
    # exist" wording a missing DATABASE uses (`FATAL: database "x" does not
    # exist`). "relation "/"column " must be checked before the generic
    # "does not exist" below, or a rejected query is misreported as a missing
    # database — a WRONG class, which is worse than `unknown failure` because
    # it misleads rather than merely saying less. See
    # tests/test_failure_classes.py::MarkerOrderingTests.
    ("relation ", "the query was rejected"),
    ("column ", "the query was rejected"),
    ("does not exist", "the named database does not exist"),
    ("permission denied", "permission denied by the server"),
    ("must be owner", "permission denied by the server"),
    ("ssl", "TLS/SSL negotiation failed"),
    ("certificate", "TLS/SSL negotiation failed"),
    ("syntax error", "the query was rejected"),
)


def classify(foreign_text: str | None) -> str:
    """A member of `FAILURE_CLASSES` describing `foreign_text`.

    The input is read and never echoed: every return value is a literal from
    `_MARKERS`/`UNKNOWN` above, so no substring of the argument can reach the
    result. That property is the whole point of this function and is asserted
    directly in `tests/test_failure_classes.py`.
    """
    if not foreign_text:
        return UNKNOWN
    haystack = foreign_text.lower()
    for marker, klass in _MARKERS:
        if marker in haystack:
            return klass
    return UNKNOWN


def describe(operation: str, foreign_text: str | None) -> str:
    """A complete, safe one-line failure message.

    `operation` is a short phrase THIS REPO authors (e.g. "postgres query") —
    never a value read from the environment, a DSN, or a foreign process.
    """
    return f"{operation} failed: {classify(foreign_text)}"
