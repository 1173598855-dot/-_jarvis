import unittest

from core.brain.context_budget import ContextBudgetMonitor, FallbackContextBudgetProvider
from core.contracts.run_state import ContextLevel


class TestContextBudgetMonitor(unittest.TestCase):
    def test_exact_boundaries_map_to_expected_levels(self):
        monitor = ContextBudgetMonitor()
        cases = (
            (64, ContextLevel.GREEN),
            (65, ContextLevel.AMBER),
            (80, ContextLevel.ORANGE),
            (90, ContextLevel.RED),
        )
        for used, expected in cases:
            with self.subTest(used=used):
                snapshot = FallbackContextBudgetProvider(
                    total_tokens=100,
                    estimate=lambda used=used: used,
                ).snapshot()
                self.assertEqual(monitor.level_for(snapshot), expected)

    def test_observe_emits_only_when_level_changes(self):
        monitor = ContextBudgetMonitor()
        green = FallbackContextBudgetProvider(100, lambda: 10).snapshot()
        red = FallbackContextBudgetProvider(100, lambda: 95).snapshot()

        self.assertIsNone(monitor.observe(green))
        event = monitor.observe(red)
        self.assertEqual(event.previous, ContextLevel.GREEN)
        self.assertEqual(event.current, ContextLevel.RED)
        self.assertIsNone(monitor.observe(red))

    def test_initial_non_green_observation_emits_from_green(self):
        monitor = ContextBudgetMonitor()
        amber = FallbackContextBudgetProvider(100, lambda: 70).snapshot()

        event = monitor.observe(amber)

        self.assertEqual(event.previous, ContextLevel.GREEN)
        self.assertEqual(event.current, ContextLevel.AMBER)

    def test_runtime_reader_is_preferred_when_valid(self):
        provider = FallbackContextBudgetProvider(
            100,
            lambda: 20,
            runtime_reader=lambda: (75, 200),
        )

        snapshot = provider.snapshot()

        self.assertEqual((snapshot.used_tokens, snapshot.total_tokens), (75, 200))
        self.assertEqual(snapshot.source, "runtime")

    def test_invalid_runtime_reader_falls_back_and_clamps_estimate(self):
        provider = FallbackContextBudgetProvider(
            100,
            lambda: 150,
            runtime_reader=lambda: (101, 100),
        )

        snapshot = provider.snapshot()

        self.assertEqual((snapshot.used_tokens, snapshot.total_tokens), (100, 100))
        self.assertEqual(snapshot.source, "estimate")

    def test_invalid_usage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "total_tokens"):
            FallbackContextBudgetProvider(0, lambda: 1).snapshot()
        with self.assertRaisesRegex(ValueError, "used_tokens"):
            FallbackContextBudgetProvider(100, lambda: -1).snapshot()

    def test_invalid_threshold_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "threshold"):
            ContextBudgetMonitor(amber=0.8, orange=0.7, red=0.9)


if __name__ == "__main__":
    unittest.main()
