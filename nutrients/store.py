import json
import uuid
from dataclasses import asdict, fields
from pathlib import Path

from gi.repository import GLib

from .models import DEFAULT_GOALS, DEFAULT_SETTINGS, MealEntry, NUTRIENTS


class Store:
    def __init__(self):
        root = Path(GLib.get_user_data_dir()) / "nutrient-tracker"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "data.json"
        self.entries = []
        self.goals = DEFAULT_GOALS.copy()
        self.settings = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        if not self.path.exists():
            self.save()
            return

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}

        self.goals = DEFAULT_GOALS | data.get("goals", {})
        self.settings = DEFAULT_SETTINGS | data.get("settings", {})
        self.entries = [
            MealEntry(**entry)
            for entry in data.get("entries", [])
            if self._is_valid_entry(entry)
        ]

    def save(self):
        data = {
            "goals": self.goals,
            "settings": self.settings,
            "entries": [asdict(entry) for entry in self.entries],
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

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

    @staticmethod
    def _is_valid_entry(entry):
        return all(field.name in entry for field in fields(MealEntry))
