import shutil
import sqlite3
import uuid
from dataclasses import astuple
from pathlib import Path

from gi.repository import GLib

from .models import DEFAULT_GOALS, DEFAULT_SETTINGS, MealEntry, NUTRIENTS, Recipe


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    grams REAL NOT NULL DEFAULT 0,
    calories REAL NOT NULL,
    protein REAL NOT NULL,
    carbs REAL NOT NULL,
    fat REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_day_idx ON entries (day);
CREATE TABLE IF NOT EXISTS goals (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    grams REAL NOT NULL DEFAULT 0,
    calories REAL NOT NULL,
    protein REAL NOT NULL,
    carbs REAL NOT NULL,
    fat REAL NOT NULL
);
"""


class Store:
    def __init__(self):
        data_home = Path(GLib.get_user_data_dir())
        root = data_home / "nomnomus"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "data.sqlite3"
        legacy_path = data_home / "nutrient-tracker" / "data.sqlite3"
        if not self.path.exists() and legacy_path.exists():
            shutil.copy2(legacy_path, self.path)
        self.entries = []
        self.recipes = []
        self.goals = DEFAULT_GOALS.copy()
        self.settings = DEFAULT_SETTINGS.copy()
        is_new_database = not self.path.exists()
        self._initialize_database()
        self.load()
        if is_new_database:
            self.save()

    def load(self):
        with sqlite3.connect(self.path) as connection:
            self._migrate_database(connection)
            goals = dict(connection.execute("SELECT key, value FROM goals"))
            settings = dict(connection.execute("SELECT key, value FROM settings"))
            rows = connection.execute(
                """
                SELECT id, day, name, grams, calories, protein, carbs, fat
                FROM entries
                ORDER BY rowid
                """
            )
            entries = [MealEntry(*row) for row in rows]
            recipe_rows = connection.execute(
                """
                SELECT id, name, grams, calories, protein, carbs, fat
                FROM recipes
                ORDER BY rowid
                """
            )
            recipes = [Recipe(*row) for row in recipe_rows]

        self.goals = DEFAULT_GOALS | goals
        self.settings = DEFAULT_SETTINGS | settings
        self.entries = entries
        self.recipes = recipes

    def save(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM entries")
            connection.execute("DELETE FROM recipes")
            connection.execute("DELETE FROM goals")
            connection.execute("DELETE FROM settings")
            connection.executemany(
                """
                INSERT INTO entries (id, day, name, grams, calories, protein, carbs, fat)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (astuple(entry) for entry in self.entries),
            )
            connection.executemany(
                """
                INSERT INTO recipes (id, name, grams, calories, protein, carbs, fat)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (astuple(recipe) for recipe in self.recipes),
            )
            connection.executemany(
                "INSERT INTO goals (key, value) VALUES (?, ?)",
                self.goals.items(),
            )
            connection.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                self.settings.items(),
            )

    def _initialize_database(self):
        with sqlite3.connect(self.path) as connection:
            connection.executescript(SCHEMA)
            self._migrate_database(connection)

    def _migrate_database(self, connection):
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(entries)")
        }
        if "grams" not in columns:
            connection.execute(
                "ALTER TABLE entries ADD COLUMN grams REAL NOT NULL DEFAULT 0"
            )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                grams REAL NOT NULL DEFAULT 0,
                calories REAL NOT NULL,
                protein REAL NOT NULL,
                carbs REAL NOT NULL,
                fat REAL NOT NULL
            );
            """
        )

    def add_entry(self, day, name, grams, calories, protein, carbs, fat):
        entry = MealEntry(
            id=str(uuid.uuid4()),
            day=day,
            name=name.strip() or "Food",
            grams=grams,
            calories=calories,
            protein=protein,
            carbs=carbs,
            fat=fat,
        )
        self.entries.append(entry)
        self.save()
        return entry

    def update_entry(self, entry_id, day, name, grams, calories, protein, carbs, fat):
        for entry in self.entries:
            if entry.id == entry_id:
                entry.day = day
                entry.name = name.strip() or "Food"
                entry.grams = grams
                entry.calories = calories
                entry.protein = protein
                entry.carbs = carbs
                entry.fat = fat
                self.save()
                return entry
        return None

    def delete_entry(self, entry_id):
        self.entries = [entry for entry in self.entries if entry.id != entry_id]
        self.save()

    def add_recipe(self, name, grams, calories, protein, carbs, fat):
        recipe = Recipe(
            id=str(uuid.uuid4()),
            name=name.strip() or "Recipe",
            grams=grams,
            calories=calories,
            protein=protein,
            carbs=carbs,
            fat=fat,
        )
        self.recipes.append(recipe)
        self.save()
        return recipe

    def add_recipe_from_entry(self, entry):
        existing = self.recipe_for_entry(entry)
        if existing:
            return existing
        return self.add_recipe(
            entry.name,
            entry.grams,
            entry.calories,
            entry.protein,
            entry.carbs,
            entry.fat,
        )

    def update_recipe(self, recipe_id, name, grams, calories, protein, carbs, fat):
        for recipe in self.recipes:
            if recipe.id == recipe_id:
                recipe.name = name.strip() or "Recipe"
                recipe.grams = grams
                recipe.calories = calories
                recipe.protein = protein
                recipe.carbs = carbs
                recipe.fat = fat
                self.save()
                return recipe
        return None

    def delete_recipe(self, recipe_id):
        self.recipes = [recipe for recipe in self.recipes if recipe.id != recipe_id]
        self.save()

    def delete_recipe_for_entry(self, entry):
        recipe = self.recipe_for_entry(entry)
        if recipe:
            self.delete_recipe(recipe.id)
            return recipe
        return None

    def recipe_for_entry(self, entry):
        for recipe in self.recipes:
            if (
                recipe.name == entry.name
                and _same_amount(recipe.grams, entry.grams)
                and _same_amount(recipe.calories, entry.calories)
                and _same_amount(recipe.protein, entry.protein)
                and _same_amount(recipe.carbs, entry.carbs)
                and _same_amount(recipe.fat, entry.fat)
            ):
                return recipe
        return None

    def recipes_matching(self, query):
        query = query.strip().casefold()
        if len(query) < 3:
            return []
        return [recipe for recipe in self.recipes if query in recipe.name.casefold()]

    def entries_for(self, day):
        return [entry for entry in self.entries if entry.day == day]

    def totals_for(self, day):
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        for entry in self.entries_for(day):
            totals["calories"] += entry.calories
            totals["protein"] += entry.protein
            totals["carbs"] += entry.carbs
            totals["fat"] += entry.fat
        return totals

    def logged_days_for_month(self, year, month):
        prefix = f"{year:04d}-{month:02d}-"
        return sorted({entry.day for entry in self.entries if entry.day.startswith(prefix)})


def _same_amount(left, right):
    return round(float(left or 0), 3) == round(float(right or 0), 3)
