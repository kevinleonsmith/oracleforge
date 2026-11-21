"""CLI surface tests — the dry-run tick runs without a chain or network."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

from oracleforge_resolver.cli import main  # noqa: E402


def _run(*argv) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(list(argv))
    assert rc == 0, f"exit {rc}"
    return buf.getvalue()


class TablelandOutputTests(unittest.TestCase):
    def test_binary_tableland_prints_report_and_markets_transition(self):
        out = _run("--dry-run", "--tableland")
        self.assertIn("settlement -> Tableland", out)
        self.assertIn("INSERT INTO oracle_reports", out)
        # the catalog transition is surfaced too, not just the evidence row
        self.assertIn("UPDATE markets SET status='RESOLVED'", out)

    def test_scalar_tableland_prints_statements(self):
        out = _run("--dry-run", "--scalar", "--tableland")
        self.assertIn("settlement -> Tableland", out)
        self.assertIn("INSERT INTO oracle_reports", out)
        self.assertIn("UPDATE markets", out)

    def test_categorical_tableland_prints_statements(self):
        out = _run("--dry-run", "--categorical", "--tableland")
        self.assertIn("INSERT INTO oracle_reports", out)
        self.assertIn("UPDATE markets", out)

    def test_without_tableland_no_sql_block(self):
        out = _run("--dry-run")
        self.assertNotIn("settlement -> Tableland", out)
        self.assertNotIn("INSERT INTO oracle_reports", out)


if __name__ == "__main__":
    unittest.main()
