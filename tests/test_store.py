import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nomnomus.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.previous_data_home = os.environ.get("XDG_DATA_HOME")
        self.data_home = tempfile.TemporaryDirectory()
        os.environ["XDG_DATA_HOME"] = self.data_home.name
        self.data_dir_patch = patch(
            "nomnomus.store.GLib.get_user_data_dir",
            return_value=self.data_home.name,
        )
        self.data_dir_patch.start()

    def tearDown(self):
        self.data_dir_patch.stop()
        self.data_home.cleanup()
        if self.previous_data_home is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self.previous_data_home

    def test_store_persists_entries_goals_and_settings_in_sqlite(self):
        store = Store()
        store.add_entry("2026-06-01", "Lunch", 250, 500, 25, 60, 18)
        store.goals["protein"] = 140
        store.settings["range_percent"] = 20
        store.save()

        reloaded = Store()

        self.assertEqual(reloaded.path.name, "data.sqlite3")
        self.assertEqual(reloaded.path.parent.name, "nomnomus")
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0].name, "Lunch")
        self.assertEqual(reloaded.entries[0].grams, 250)
        self.assertEqual(reloaded.goals["protein"], 140)
        self.assertEqual(reloaded.settings["range_percent"], 20)
        with sqlite3.connect(reloaded.path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        self.assertEqual(count, 1)

    def test_store_copies_legacy_database_on_first_launch(self):
        store = Store()
        store.add_entry("2026-06-01", "Lunch", 250, 500, 25, 60, 18)

        legacy_dir = Path(self.data_home.name) / "nutrient-tracker"
        legacy_dir.mkdir()
        store.path.replace(legacy_dir / "data.sqlite3")

        reloaded = Store()

        self.assertTrue(reloaded.path.exists())
        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0].name, "Lunch")
        self.assertEqual(reloaded.entries[0].grams, 250)

    def test_store_migrates_entries_without_grams(self):
        store = Store()
        with sqlite3.connect(store.path) as connection:
            connection.execute("DROP TABLE entries")
            connection.execute(
                """
                CREATE TABLE entries (
                    id TEXT PRIMARY KEY,
                    day TEXT NOT NULL,
                    name TEXT NOT NULL,
                    calories REAL NOT NULL,
                    protein REAL NOT NULL,
                    carbs REAL NOT NULL,
                    fat REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO entries (id, day, name, calories, protein, carbs, fat)
                VALUES ('entry-1', '2026-06-01', 'Old lunch', 500, 25, 60, 18)
                """
            )

        reloaded = Store()

        self.assertEqual(len(reloaded.entries), 1)
        self.assertEqual(reloaded.entries[0].name, "Old lunch")
        self.assertEqual(reloaded.entries[0].grams, 0)

    def test_store_persists_and_matches_recipes(self):
        store = Store()
        entry = store.add_entry("2026-06-01", "Lunch", 250, 500, 25, 60, 18)

        recipe = store.add_recipe_from_entry(entry)
        reloaded = Store()

        self.assertEqual(len(reloaded.recipes), 1)
        self.assertEqual(reloaded.recipes[0].name, "Lunch")
        self.assertEqual(reloaded.recipes[0].grams, 250)
        self.assertEqual(reloaded.recipes_matching("lun")[0].id, recipe.id)
        self.assertIsNotNone(reloaded.recipe_for_entry(entry))

        reloaded.update_recipe(recipe.id, "Lunch bowl", 300, 600, 30, 70, 20)
        self.assertEqual(reloaded.recipes[0].name, "Lunch bowl")

        reloaded.delete_recipe(recipe.id)
        self.assertEqual(reloaded.recipes, [])

    def test_store_deletes_recipe_for_entry(self):
        store = Store()
        entry = store.add_entry("2026-06-01", "Lunch", 250, 500, 25, 60, 18)
        store.add_recipe_from_entry(entry)

        removed = store.delete_recipe_for_entry(entry)

        self.assertEqual(removed.name, "Lunch")
        self.assertEqual(store.recipes, [])

if __name__ == "__main__":
    unittest.main()
