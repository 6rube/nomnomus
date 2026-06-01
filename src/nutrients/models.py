from dataclasses import dataclass


@dataclass
class MealEntry:
    id: str
    day: str
    name: str
    calories: float
    protein: float
    carbs: float
    fat: float


DEFAULT_GOALS = {
    "calories": 2200.0,
    "protein": 120.0,
    "carbs": 250.0,
    "fat": 70.0,
}


NUTRIENTS = tuple(DEFAULT_GOALS.keys())

NUTRIENT_LABELS = {
    "calories": ("Calories", "kcal"),
    "protein": ("Protein", "g"),
    "carbs": ("Carbs", "g"),
    "fat": ("Fat", "g"),
}


DEFAULT_SETTINGS = {
    "range_percent": 15.0,
}


def calories_from_macros(protein, carbs, fat):
    return protein * 4 + carbs * 4 + fat * 9
