"""Content-addressing tests — the integrity guarantee."""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_archiver.canonical import canonical_bytes, content_hash  # noqa: E402


class CanonicalTests(unittest.TestCase):
    def test_key_order_invariant(self):
        a = {"b": 2, "a": 1, "n": {"y": [3, 2, 1], "x": True}}
        b = {"n": {"x": True, "y": [3, 2, 1]}, "a": 1, "b": 2}
        self.assertEqual(content_hash(a), content_hash(b))

    def test_distinct_data_distinct_hash(self):
        self.assertNotEqual(content_hash({"x": 1}), content_hash({"x": 2}))

    def test_hash_is_sha256_of_canonical(self):
        obj = {"market_id": "0xabc", "outcome": 1}
        self.assertEqual(content_hash(obj), "0x" + hashlib.sha256(canonical_bytes(obj)).hexdigest())

    def test_no_whitespace_and_sorted(self):
        self.assertEqual(canonical_bytes({"b": 1, "a": 2}), b'{"a":2,"b":1}')


if __name__ == "__main__":
    unittest.main()
