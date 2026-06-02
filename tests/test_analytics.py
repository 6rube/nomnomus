from calendar import monthrange
from datetime import date
import os
import tempfile
from types import SimpleNamespace
import unittest

from nomnomus.analytics import heat_class, month_summary
from nomnomus.models import DEFAULT_SETTINGS, calories_from_macros
from nomnomus.store import Store


class FakeStore:
    def __init__(self):
        self.goals = {
            "calories": 1000.0,
            "protein": 100.0,
            "carbs": 100.0,
            "fat": 100.0,
        }
        self.settings = DEFAULT_SETTINGS.copy()
        self.entries = []

    def entries_for(self, day):
        return [entry for entry in self.entries if entry.day == day]

    def logged_days_for_month(self, year, month):
        prefix = f"{year:04d}-{month:02d}-"
        return sorted({entry.day for entry in self.entries if entry.day.startswith(prefix)})

    def totals_for(self, day):
        totals = dict.fromkeys(self.goals.keys(), 0.0)
        for entry in self.entries_for(day):
            totals["calories"] += entry.calories
            totals["protein"] += entry.protein
            totals["carbs"] += entry.carbs
            totals["fat"] += entry.fat
        return totals


def entry(day, calories, protein, carbs, fat):
    return SimpleNamespace(
        day=day,
        calories=calories,
        protein=protein,
        carbs=carbs,
        fat=fat,
    )


class AnalyticsTest(unittest.TestCase):
    def test_calories_are_calculated_from_macros(self):
        self.assertEqual(calories_from_macros(10, 20, 5), 165)

    def test_heat_scale_uses_distance_from_goal_not_direction(self):
        self.assertEqual(heat_class({"calories": 0.10}, 15), "heat-ok")
        self.assertEqual(heat_class({"calories": -0.25}, 15), "heat-warm")
        self.assertEqual(heat_class({"calories": 0.50}, 15), "heat-hot")
        self.assertEqual(heat_class({"calories": -0.80}, 15), "heat-very-hot")
        self.assertEqual(heat_class({"calories": 1.00}, 15), "heat-max")

    def test_untracked_days_are_max_heat(self):
        store = FakeStore()

        summary = month_summary(store, 2024, 2)

        self.assertEqual(summary["daily"]["2024-02-01"]["heat_class"], "heat-max")

    def test_future_days_in_current_month_are_not_counted(self):
        today = date.today()
        if today.day == monthrange(today.year, today.month)[1]:
            self.skipTest("Current month has no future day left")

        store = FakeStore()
        next_day = today.replace(day=today.day + 1).isoformat()
        store.entries = [entry(next_day, 1000, 100, 100, 100)]

        summary = month_summary(store, today.year, today.month)

        self.assertEqual(summary["logged_days"], 0)
        self.assertFalse(summary["daily"][next_day]["is_counted"])
        self.assertEqual(summary["daily"][next_day]["heat_class"], "heat-future")

    def test_sparse_current_month_compares_totals_to_month_to_date(self):
        store = FakeStore()
        today = date.today()
        day = f"{today.year:04d}-{today.month:02d}-01"
        store.entries = [entry(day, 1000, 100, 100, 100)]

        summary = month_summary(store, today.year, today.month)

        self.assertEqual(summary["logged_days"], 1)
        self.assertEqual(summary["ok_days"], 1)
        self.assertEqual(summary["comparison_days"], today.day)
        self.assertEqual(summary["under"]["calories"], 1000 * (today.day - 1))

    def test_store_updates_existing_entry(self):
        previous_data_home = os.environ.get("XDG_DATA_HOME")
        try:
            with tempfile.TemporaryDirectory() as data_home:
                os.environ["XDG_DATA_HOME"] = data_home
                store = Store()
                store.entries = []
                added = store.add_entry("2026-05-27", "Old", 100, 10, 10, 2)

                updated = store.update_entry(added.id, "2026-05-27", "New", 200, 20, 20, 4)

                self.assertIsNotNone(updated)
                self.assertEqual(len(store.entries), 1)
                self.assertEqual(store.entries[0].name, "New")
                self.assertEqual(store.entries[0].calories, 200)
        finally:
            if previous_data_home is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = previous_data_home

    def test_sparse_past_month_compares_totals_to_full_month(self):
        store = FakeStore()
        store.entries = [entry("2024-02-01", 1000, 100, 100, 100)]

        summary = month_summary(store, 2024, 2)

        self.assertEqual(summary["logged_days"], 1)
        self.assertEqual(summary["ok_days"], 1)
        self.assertEqual(summary["comparison_days"], 29)
        self.assertEqual(summary["under"]["calories"], 28000)


if __name__ == "__main__":
    unittest.main()
