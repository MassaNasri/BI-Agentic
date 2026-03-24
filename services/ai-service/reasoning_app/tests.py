import unittest

from reasoning_app.llm_intent_client import is_force_analytical


class ReasoningRulesTests(unittest.TestCase):
    def test_analytical_keyword_guard(self):
        self.assertTrue(is_force_analytical("show top 5 regions by population"))
        self.assertFalse(is_force_analytical("hello how are you"))
