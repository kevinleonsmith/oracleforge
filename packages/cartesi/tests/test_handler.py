"""Off-machine tests for the Cartesi dApp handler.

Verifies the deterministic request->output logic without Docker or the RISC-V
machine. The forecasting core lives in ../../ai-market-generator, and the handler
in the parent dir, so both are added to sys.path here.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))  # handler.py
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "ai-market-generator")))

from handler import hex_to_str, process, str_to_hex  # noqa: E402


class HexTests(unittest.TestCase):
    def test_roundtrip(self):
        s = json.dumps({"op": "forecast", "question": "Will X?"})
        self.assertEqual(hex_to_str(str_to_hex(s)), s)

    def test_hex_is_0x_prefixed(self):
        self.assertTrue(str_to_hex("hi").startswith("0x"))


class ForecastTests(unittest.TestCase):
    REQ = {"op": "forecast", "question": "Will EUR/USD close above 1.10?", "priors": [0.4], "samples": 20000}

    def test_advance_emits_notice(self):
        out = process(self.REQ, inspect=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "notice")  # committed on advance
        p = out[0]["payload"]
        self.assertTrue(0 <= p["prob_bps"] <= 10000)
        self.assertTrue(p["input_hash"].startswith("0x"))

    def test_inspect_emits_report(self):
        out = process(self.REQ, inspect=True)
        self.assertEqual(out[0]["kind"], "report")  # read-only on inspect

    def test_deterministic_across_calls(self):
        a = process(self.REQ, inspect=False)[0]["payload"]
        b = process(self.REQ, inspect=False)[0]["payload"]
        self.assertEqual(a["prob_bps"], b["prob_bps"])
        self.assertEqual(a["seed"], b["seed"])  # seed derived from inputs

    def test_positive_prior_leans_yes(self):
        pos = process({**self.REQ, "priors": [0.9]}, inspect=False)[0]["payload"]["prob_bps"]
        neg = process({**self.REQ, "priors": [-0.9]}, inspect=False)[0]["payload"]["prob_bps"]
        self.assertGreater(pos, neg)


class BayesTests(unittest.TestCase):
    def test_bayes_update(self):
        out = process({"op": "bayes", "prior_prob": 0.5, "likelihood_ratio": 3.0}, inspect=False)
        self.assertEqual(out[0]["kind"], "notice")
        self.assertGreater(out[0]["payload"]["posterior"], 0.5)


class ErrorTests(unittest.TestCase):
    def test_unknown_op_reports_error(self):
        out = process({"op": "frobnicate"}, inspect=False)
        self.assertEqual(out[0]["kind"], "report")
        self.assertIn("error", out[0]["payload"])

    def test_missing_field_reports_error(self):
        out = process({"op": "forecast"}, inspect=False)  # no 'question'
        self.assertEqual(out[0]["kind"], "report")
        self.assertIn("error", out[0]["payload"])


if __name__ == "__main__":
    unittest.main()
