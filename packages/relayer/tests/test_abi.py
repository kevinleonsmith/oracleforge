"""Tests for keccak256 and ABI encoding — the parts that must match Solidity."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_relayer import abi  # noqa: E402
from oracleforge_relayer.keccak import keccak256_hex  # noqa: E402


class KeccakTests(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(
            keccak256_hex(b""),
            "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )
        self.assertEqual(
            keccak256_hex(b"abc"),
            "0x4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
        )


class OracleParamsTests(unittest.TestCase):
    def test_length_is_160_bytes(self):
        enc = abi.encode_oracle_params(
            "0x000000000000000000000000000000000000Fe01",
            "0x0000000000000000000000000000000000000000",
            110_000_000, 0, 3600,
        )
        self.assertTrue(enc.startswith("0x"))
        self.assertEqual(len(enc) - 2, 160 * 2)  # 5 words * 32 bytes, hex

    def test_word_layout(self):
        enc = abi.encode_oracle_params(
            "0x00000000000000000000000000000000000000aa",
            "0x00000000000000000000000000000000000000bb",
            260, 1, 3600,
        )
        body = enc[2:]
        words = [body[i:i + 64] for i in range(0, len(body), 64)]
        self.assertTrue(words[0].endswith("aa"))                 # feed, right-aligned
        self.assertTrue(words[1].endswith("bb"))                 # fallback
        self.assertEqual(int(words[2], 16), 260)                 # threshold
        self.assertEqual(int(words[3], 16), 1)                   # comparator
        self.assertEqual(int(words[4], 16), 3600)                # maxStale

    def test_negative_threshold_twos_complement(self):
        enc = abi.encode_oracle_params(
            "0x00000000000000000000000000000000000000aa",
            "0x0000000000000000000000000000000000000000",
            -5, 0, 0,
        )
        word = enc[2:][128:192]
        self.assertEqual(word, "f" * 61 + "ffb")  # -5 as int256 two's complement

    def test_bad_comparator(self):
        with self.assertRaises(ValueError):
            abi.encode_oracle_params("0x00", "0x00", 1, 2, 0)


class MarketIdTests(unittest.TestCase):
    def test_question_hash_is_keccak_of_text(self):
        self.assertEqual(abi.question_hash("abc"), keccak256_hex(b"abc"))

    def test_market_id_matches_packed_keccak(self):
        qh = abi.question_hash("Will EUR/USD close above 1.10?")
        close_at = 1_740_000_000
        chain_id = 10200
        # recompute the packed preimage independently
        packed = bytes.fromhex(qh[2:]) + close_at.to_bytes(8, "big") + chain_id.to_bytes(32, "big")
        self.assertEqual(abi.market_id(qh, close_at, chain_id), keccak256_hex(packed))
        # deterministic
        self.assertEqual(
            abi.market_id(qh, close_at, chain_id), abi.market_id(qh, close_at, chain_id)
        )


if __name__ == "__main__":
    unittest.main()
