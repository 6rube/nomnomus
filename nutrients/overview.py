from calendar import month_name, monthrange
from datetime import date

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk

from .analytics import month_summary
from .models import NUTRIENT_LABELS


class MonthOverviewDialog(Adw.Dialog):
    def __init__(self, parent, store, selected_day, on_day_selected):
        super().__init__()
        self.store = store
        self.on_day_selected = on_day_selected
        self.year = selected_day.year
        self.month = selected_day.month

        self.set_title("Month Overview")
        self.set_content_width(400)
        if hasattr(self, "set_content_height"):
            self.set_content_height(620)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda _button: self.close())
        header.pack_start(close)

        clamp = Adw.Clamp(maximum_size=400, tightening_threshold=320)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(clamp)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.content.set_margin_top(10)
        self.content.set_margin_bottom(12)
        self.content.set_margin_start(10)
        self.content.set_margin_end(10)
        clamp.set_child(self.content)

        month_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        previous_button = Gtk.Button(icon_name="go-previous-symbolic")
        previous_button.set_tooltip_text("Previous month")
        previous_button.connect("clicked", self._change_month, -1)
        self.month_label = Gtk.Label(hexpand=True)
        self.month_label.add_css_class("heading")
        next_button = Gtk.Button(icon_name="go-next-symbolic")
        next_button.set_tooltip_text("Next month")
        next_button.connect("clicked", self._change_month, 1)
        month_controls.append(previous_button)
        month_controls.append(self.month_label)
        month_controls.append(next_button)
        self.content.append(month_controls)

        self.summary_label = Gtk.Label(xalign=0, wrap=True)
        self.summary_label.add_css_class("caption-heading")
        self.content.append(self.summary_label)

        self.calendar_grid = Gtk.Grid(
            column_spacing=4,
            row_spacing=4,
            column_homogeneous=True,
            row_homogeneous=True,
        )
        self.content.append(self.calendar_grid)

        self.totals_grid = Gtk.Grid(
            column_spacing=8,
            row_spacing=4,
            column_homogeneous=True,
        )
        self.totals_grid.add_css_class("compact-totals")
        self.content.append(self.totals_grid)

        toolbar_view.set_content(scroller)
        self.set_child(toolbar_view)
        self.refresh()
        self.present(parent)

    def refresh(self):
        summary = month_summary(self.store, self.year, self.month)
        range_percent = self.store.settings["range_percent"]
        self.month_label.set_label(f"{month_name[self.month]} {self.year}")
        self.summary_label.set_label(
            f"{summary['ok_days']} / {summary['logged_days']} logged days OK "
            f"(+/- {range_percent:.0f}%) | {summary['comparison_days']} target days"
        )
        self._draw_calendar(summary)
        self._draw_totals(summary)

    def _draw_calendar(self, summary):
        while child := self.calendar_grid.get_first_child():
            self.calendar_grid.remove(child)

        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        for column, weekday in enumerate(weekdays):
            label = Gtk.Label(label=weekday)
            label.add_css_class("caption-heading")
            self.calendar_grid.attach(label, column, 0, 1, 1)

        first_weekday, days_in_month = monthrange(self.year, self.month)
        for day_number in range(1, days_in_month + 1):
            day = date(self.year, self.month, day_number)
            row = ((first_weekday + day_number - 1) // 7) + 1
            column = (first_weekday + day_number - 1) % 7
            day_info = summary["daily"][day.isoformat()]

            tile = Gtk.Button(label=str(day_number))
            tile.add_css_class("flat")
            tile.add_css_class("heat-day")
            tile.add_css_class(day_info["heat_class"])
            tile.set_tooltip_text(self._tooltip(day, day_info))
            tile.connect("clicked", self._select_day, day)
            self.calendar_grid.attach(tile, column, row, 1, 1)

    def _draw_totals(self, summary):
        while child := self.totals_grid.get_first_child():
            self.totals_grid.remove(child)

        for column, text in enumerate(("Nutrient", "Total", "Over", "Under")):
            label = Gtk.Label(label=text, xalign=0)
            label.add_css_class("caption-heading")
            self.totals_grid.attach(label, column, 0, 1, 1)

        for row, (key, (title, unit)) in enumerate(NUTRIENT_LABELS.items(), start=1):
            values = (
                title,
                f"{summary['consumed'][key]:.0f} {unit}",
                f"{summary['over'][key]:.0f}",
                f"{summary['under'][key]:.0f}",
            )
            for column, text in enumerate(values):
                label = Gtk.Label(label=text, xalign=0)
                label.add_css_class("caption")
                self.totals_grid.attach(label, column, row, 1, 1)

    def _tooltip(self, day, day_info):
        if not day_info["is_counted"]:
            return f"{day.strftime('%b %-d')}: not counted yet"
        if not day_info["has_entries"]:
            return f"{day.strftime('%b %-d')}: no entries"
        totals = day_info["totals"]
        status = "OK" if day_info["ok"] else "Outside range"
        return (
            f"{day.strftime('%b %-d')}: {status}\n"
            f"{totals['calories']:.0f} kcal, "
            f"P {totals['protein']:.0f}g, "
            f"C {totals['carbs']:.0f}g, "
            f"F {totals['fat']:.0f}g"
        )

    def _change_month(self, _button, delta):
        month = self.month + delta
        year = self.year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self.month = month
        self.year = year
        self.refresh()

    def _select_day(self, _button, selected_day):
        self.on_day_selected(selected_day)
        self.close()
