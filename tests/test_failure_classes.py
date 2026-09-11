"""Errors are an egress path too.

`Guard.scan_egress` (both phases) guards the rendered *report*. An `error:`
line is not a report and goes through no gate at all, so a message built by
interpolating a foreign process's stderr can carry anything that process
decided to print — including, as the regression below records, the operator's
database password in plaintext.

These tests hold the closed vocabulary to the one property that makes it worth
its cost: **no substring of the input can reach the output.**
"""
import unittest

from corpuslens.failure_classes import (FAILURE_CLASSES, UNKNOWN, classify,
                                        describe)

# The exact psql stderr that leaked, captured by running:
#   corpuslens run --adapter postgres "postgres://seanuser:hunter2@[bad/corpus"
# `hunter2` is a fictional password used only as a canary in these tests.
LEAKY_PSQL_STDERR = (
    'psql: error: end of string reached when looking for matching "]" in IPv6 '
    'host address in URI: "postgres://seanuser:hunter2@[bad/corpus"'
)
SECRETS_IN_IT = ("hunter2", "seanuser", "postgres://")


class ClosedVocabularyTests(unittest.TestCase):
    def test_every_classification_is_a_member_of_the_closed_list(self):
        samples = [
            LEAKY_PSQL_STDERR,
            'could not translate host name "db.internal.example.com" to address',
            'connection to server at "127.0.0.1", port 1 failed: Connection refused',
            'password authentication failed for user "seanuser"',
            'FATAL: database "corpus" does not exist',
            "permission denied for table turns",
            "SSL SYSCALL error: EOF detected",
            'syntax error at or near "SELEC"',
            "file is not a database",
            "database is locked",
            "unable to open database file",
            "no such table: turns",
            "something nobody has ever seen before",
            "",
            None,
        ]
        for s in samples:
            self.assertIn(classify(s), FAILURE_CLASSES, f"escaped the vocabulary: {s!r}")

    def test_an_unrecognized_failure_degrades_to_unknown(self):
        self.assertEqual(classify("a brand new error nobody wrote a marker for"), UNKNOWN)

    def test_empty_and_none_are_unknown(self):
        self.assertEqual(classify(""), UNKNOWN)
        self.assertEqual(classify(None), UNKNOWN)


class NoInputReachesTheOutputTests(unittest.TestCase):
    """The load-bearing property. If this suite ever fails, the gate has been
    turned back into a redactor and the whole trade has been given away."""

    def test_the_password_leak_regression(self):
        out = describe("psql", LEAKY_PSQL_STDERR)
        for secret in SECRETS_IN_IT:
            self.assertNotIn(secret, out)
        self.assertEqual(out, "psql failed: the connection string is malformed")

    def test_no_token_of_the_input_survives_classification(self):
        # stronger and more general than the regression above: assert that no
        # word of a hostile input appears in the output, for every sample
        hostile = (
            'psql: error: connection to server at "db.internal.example.com" (10.1.2.3), '
            'port 5432 failed: FATAL: password authentication failed for user "seanuser" '
            "secrettoken-xxx-EXAMPLE-xxx /home/sean-campbell/.pgpass"
        )
        out = describe("postgres query", hostile)
        for token in ("db.internal.example.com", "10.1.2.3", "5432", "seanuser",
                      "secrettoken", "/home/sean-campbell", ".pgpass"):
            self.assertNotIn(token, out)

    def test_output_is_exactly_operation_plus_one_class(self):
        for sample in (LEAKY_PSQL_STDERR, "connection refused", "anything at all"):
            out = describe("psql", sample)
            self.assertTrue(out.startswith("psql failed: "))
            self.assertIn(out[len("psql failed: "):], FAILURE_CLASSES)


class ClassificationAccuracyTests(unittest.TestCase):
    """Classification has to be right often enough to be worth the lost detail —
    otherwise every failure reads 'unknown failure' and operators stop reading.
    """

    def test_real_psql_failures_classify(self):
        cases = [
            (LEAKY_PSQL_STDERR, "the connection string is malformed"),
            ('psql: error: could not translate host name "h" to address: '
             "No address associated with hostname", "could not resolve the host name"),
            ('connection to server at "127.0.0.1", port 1 failed: Connection refused',
             "connection refused"),
            ('FATAL: password authentication failed for user "seanuser"',
             "authentication failed"),
            ("ERROR: permission denied for table turns", "permission denied by the server"),
            ('ERROR: syntax error at or near "SELEC"', "the query was rejected"),
        ]
        for stderr, expected in cases:
            self.assertEqual(classify(stderr), expected, stderr)

    def test_real_sqlite_failures_classify(self):
        cases = [
            ("file is not a database", "the file is not a readable database"),
            ("database disk image is malformed", "the file is not a readable database"),
            ("database is locked", "the database is locked"),
            ("unable to open database file", "the database file could not be opened"),
            ("no such table: turns", "the query was rejected"),
        ]
        for msg, expected in cases:
            self.assertEqual(classify(msg), expected, msg)


class AdapterWiringTests(unittest.TestCase):
    """The vocabulary is only worth anything if the adapters actually route
    through it — the leak was at the call site, not in a helper."""

    def test_postgres_adapter_reports_a_closed_class(self):
        from corpuslens.ingest import postgres
        with self.assertRaises(ValueError) as cm:
            postgres._psql("postgres://seanuser:hunter2@[bad/corpus", "SELECT 1")
        msg = str(cm.exception)
        for secret in SECRETS_IN_IT:
            self.assertNotIn(secret, msg)
        self.assertIn("the connection string is malformed", msg)

    def test_sqlite_adapter_reports_a_closed_class(self):
        import tempfile, os
        from corpuslens.ingest import sqlite as sqlite_adapter
        fd, path = tempfile.mkstemp(suffix=".db")
        try:
            os.write(fd, b"definitely not a database")
            os.close(fd)
            with self.assertRaises(ValueError) as cm:
                list(sqlite_adapter.ingest(path))
            msg = str(cm.exception)
            self.assertIn("the file is not a readable database", msg)
            # the operator typed this path, so it stays — only the foreign
            # library's own text is replaced
            self.assertIn(path, msg)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
