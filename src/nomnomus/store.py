import shutil
import sqlite3
import uuid
from dataclasses import astuple
from pathlib import Path

from gi.repository import GLib

from .models import DEFAULT_GOALS, DEFAULT_SETTINGS, MealEntry, NUTRIENTS


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
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
        self.goals = DEFAULT_GOALS.copy()
        self.settings = DEFAULT_SETTINGS.copy()
        is_new_database = not self.path.exists()
        self._initialize_database()
        self.load()
        if is_new_database:
            self.save()

    def load(self):
        with sqlite3.connect(self.path) as connection:
            goals = dict(connection.execute("SELECT key, value FROM goals"))
            settings = dict(connection.execute("SELECT key, value FROM settings"))
            rows = connection.execute(
                """
                SELECT id, day, name, calories, protein, carbs, fat
                FROM entries
                ORDER BY rowid
                """
            )
            entries = [MealEntry(*row) for row in rows]

        self.goals = DEFAULT_GOALS | goals
        self.settings = DEFAULT_SETTINGS | settings
        self.entries = entries

    def save(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM entries")
            connection.execute("DELETE FROM goals")
            connection.execute("DELETE FROM settings")
            connection.executemany(
                """
                INSERT INTO entries (id, day, name, calories, protein, carbs, fat)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (astuple(entry) for entry in self.entries),
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

    def add_entry(self, day, name, calories, protein, carbs, fat):
        entry = MealEntry(
            id=str(uuid.uuid4()),
            day=day,
            name=name.strip() or "Food",
            calories=calories,
            protein=protein,
            carbs=carbs,
            fat=fat,
        )
        self.entries.append(entry)
        self.save()
        return entry

    def update_entry(self, entry_id, day, name, calories, protein, carbs, fat):
        for entry in self.entries:
            if entry.id == entry_id:
                entry.day = day
                entry.name = name.strip() or "Food"
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
