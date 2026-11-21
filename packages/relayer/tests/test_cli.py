"""CLI surface tests — the dry-run paths run without a chain or network."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

from oracleforge_relayer.cli import main  # noqa: E402


def _run(*argv) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(list(argv))
    assert rc == 0, f"exit {rc}"
    return buf.getvalue()


class IndexFlagTests(unittest.TestCase):
    def test_scalar_index_prints_markets_inserts(self):
        out = _run("--dry-run", "--scalar", "--index")
        self.assertIn("index -> Tableland", out)
        self.assertIn("INSERT INTO markets", out)
        self.assertIn("'scalar'", out)  # self-describing market_type

    def test_categorical_index_prints_markets_inserts(self):
        out = _run("--dry-run", "--categorical", "--index")
        self.assertIn("INSERT INTO markets", out)
        self.assertIn("'categorical'", out)

    def test_without_index_flag_no_index_section(self):
        out = _run("--dry-run", "--scalar")
        self.assertNotIn("index -> Tableland", out)
        self.assertIn("scalar market(s) would be submitted", out)


class BinaryIndexTests(unittest.TestCase):
    def test_binary_index_includes_a_prediction_insert(self):
        # the generator path is deterministic and needs no network; a binary market
        # carries a forecast, so the index SQL includes a predictions row too.
        out = _run("--dry-run", "--index", "--limit", "1")
        self.assertIn("index -> Tableland", out)
        self.assertIn("INSERT INTO markets", out)
        self.assertIn("INSERT INTO predictions", out)


if __name__ == "__main__":
    unittest.main()
