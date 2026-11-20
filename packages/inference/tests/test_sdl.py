"""Akash SDL structure tests."""
import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "deploy")))

from sdl import build_sdl  # noqa: E402


class SdlTests(unittest.TestCase):
    def test_required_top_level_keys(self):
        sdl = build_sdl()
        for key in ("version", "services", "profiles", "deployment"):
            self.assertIn(key, sdl)
        self.assertEqual(sdl["version"], "2.0")

    def test_service_exposes_port_globally(self):
        svc = build_sdl(port=8070)["services"]["inference"]
        self.assertIn("image", svc)
        exp = svc["expose"][0]
        self.assertEqual(exp["port"], 8070)
        self.assertEqual(exp["as"], 80)
        self.assertTrue(exp["to"][0]["global"])

    def test_gpu_profile_requests_nvidia(self):
        res = build_sdl(gpu=True, gpu_models=["a100"])["profiles"]["compute"]["inference"]["resources"]
        self.assertIn("gpu", res)
        self.assertEqual(res["gpu"]["units"], 1)
        models = res["gpu"]["attributes"]["vendor"]["nvidia"]
        self.assertEqual(models, [{"model": "a100"}])

    def test_staging_has_no_gpu(self):
        res = build_sdl(gpu=False)["profiles"]["compute"]["inference"]["resources"]
        self.assertNotIn("gpu", res)

    def test_deployment_references_defined_profile(self):
        sdl = build_sdl()
        dep = sdl["deployment"]["inference"]["akash"]
        self.assertEqual(dep["profile"], "inference")
        self.assertIn(dep["profile"], sdl["profiles"]["compute"])
        self.assertIn("akash", sdl["profiles"]["placement"])
        self.assertGreater(dep["count"], 0)

    def test_pricing_present(self):
        pricing = build_sdl()["profiles"]["placement"]["akash"]["pricing"]["inference"]
        self.assertEqual(pricing["denom"], "uakt")
        self.assertGreater(pricing["amount"], 0)

    def test_yaml_roundtrip(self):
        sdl = build_sdl()
        self.assertEqual(yaml.safe_load(yaml.safe_dump(sdl)), sdl)


if __name__ == "__main__":
    unittest.main()
