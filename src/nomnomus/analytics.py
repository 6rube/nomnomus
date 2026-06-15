from calendar import monthrange
from datetime import date

from .models import NUTRIENTS


def nutrient_status(totals, goals, range_percent):
    tolerance = range_percent / 100.0
    deviations = {}
    ok = True

    for key in NUTRIENTS:
        goal = goals.get(key, 0)
        amount = totals.get(key, 0)
        if goal <= 0:
            deviations[key] = 0.0
            continue

        deviation = (amount - goal) / goal
        deviations[key] = deviation
        if abs(deviation) > tolerance:
            ok = False

    return ok, deviations


def heat_class(deviations, range_percent):
    worst = max(deviations.values(), key=lambda value: abs(value), default=0.0)
    tolerance = range_percent / 100.0
    severity = abs(worst)

    if severity <= tolerance:
        return "heat-ok"
    if severity >= 1.0:
        return "heat-max"
    if severity <= 0.35:
        return "heat-warm"
    if severity <= 0.65:
        return "heat-hot"
    return "heat-very-hot"


def month_summary(store, year, month):
    range_percent = store.settings["range_percent"]
    days_in_month = monthrange(year, month)[1]
    today = date.today()
    comparison_days = _comparison_days(year, month, days_in_month, today)
    counted_days = {
        date(year, month, day_number).isoformat()
        for day_number in range(1, comparison_days + 1)
    }
    month_totals = _totals_by_day_for_month(store, year, month)
    logged_days = set(month_totals) & counted_days

    daily = {}
    ok_days = 0
    over = dict.fromkeys(NUTRIENTS, 0.0)
    under = dict.fromkeys(NUTRIENTS, 0.0)
    consumed = dict.fromkeys(NUTRIENTS, 0.0)

    for day_number in range(1, days_in_month + 1):
        day = date(year, month, day_number).isoformat()
        totals = month_totals.get(day, dict.fromkeys(NUTRIENTS, 0.0))
        has_entries = day in logged_days
        is_counted = day in counted_days
        ok, deviations = nutrient_status(totals, store.goals, range_percent)

        if is_counted and has_entries:
            if ok:
                ok_days += 1

            for key in NUTRIENTS:
                consumed[key] += totals[key]

        if not is_counted:
            heat = "heat-future"
        elif has_entries:
            heat = heat_class(deviations, range_percent)
        else:
            heat = "heat-max"

        daily[day] = {
            "has_entries": has_entries,
            "is_counted": is_counted,
            "ok": ok,
            "totals": totals,
            "deviations": deviations,
            "heat_class": heat,
        }

    for key in NUTRIENTS:
        target = store.goals[key] * comparison_days
        difference = consumed[key] - target
        if difference > 0:
            over[key] = difference
        elif difference < 0:
            under[key] = abs(difference)

    return {
        "daily": daily,
        "logged_days": len(logged_days),
        "ok_days": ok_days,
        "comparison_days": comparison_days,
        "over": over,
        "under": under,
        "consumed": consumed,
    }


def _comparison_days(year, month, days_in_month, today):
    if year == today.year and month == today.month:
        return today.day
    if (year, month) < (today.year, today.month):
        return days_in_month
    return 0


def _totals_by_day_for_month(store, year, month):
    if hasattr(store, "totals_by_day_for_month"):
        return store.totals_by_day_for_month(year, month)

    prefix = f"{year:04d}-{month:02d}-"
    totals_by_day = {}
    for entry in getattr(store, "entries", ()):
        if not entry.day.startswith(prefix):
            continue
        totals = totals_by_day.setdefault(entry.day, dict.fromkeys(NUTRIENTS, 0.0))
        totals["calories"] += entry.calories
        totals["protein"] += entry.protein
        totals["carbs"] += entry.carbs
        totals["fat"] += entry.fat
    return totals_by_day
