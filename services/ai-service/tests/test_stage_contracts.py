from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("services/ai-service"))

from shared.stage_contract import normalize_stage_status, stage_allows_progress


class StageContractTests(unittest.TestCase):
    def test_normalize_stage_status_maps_legacy_routed_to_success(self):
        self.assertEqual(normalize_stage_status("routed"), "success")

    def test_stage_allows_progress_for_degraded(self):
        self.assertTrue(stage_allows_progress("degraded"))
        self.assertTrue(stage_allows_progress("success"))
        self.assertFalse(stage_allows_progress("failed"))


if __name__ == "__main__":
    unittest.main()

