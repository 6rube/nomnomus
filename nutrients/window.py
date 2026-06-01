from datetime import date, timedelta

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk

from . import APP_NAME
from .dialogs import AddEntryDialog, GoalsDialog
from .icons import choose_icon, icon_button
from .overview import MonthOverviewDialog
from .store import Store
from .widgets import EntryRow, NutrientBar


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.store = Store()
        self.selected_day = date.today()

        self.set_title(APP_NAME)
        self.set_default_size(360, 720)

        root = Adw.ToolbarView()
        self.set_content(root)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=APP_NAME))
        root.add_top_bar(header)

        previous_button = Gtk.Button(icon_name="go-previous-symbolic")
        previous_button.set_tooltip_text("Previous day")
        previous_button.connect("clicked", self._change_day, -1)
        header.pack_start(previous_button)

        next_button = Gtk.Button(icon_name="go-next-symbolic")
        next_button.set_tooltip_text("Next day")
        next_button.connect("clicked", self._change_day, 1)
        header.pack_start(next_button)

        overview_button = icon_button("x-office-calendar-symbolic", "Month")
        overview_button.set_tooltip_text("Month overview")
        overview_button.connect("clicked", self._show_month_overview)
        header.pack_end(overview_button)

        goals_button = icon_button("preferences-system-symbolic", "Goals")
        goals_button.set_tooltip_text("Daily goals")
        goals_button.connect("clicked", self._show_goals)
        header.pack_end(goals_button)

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("suggested-action")
        add_button.set_tooltip_text("Add food")
        add_button.connect("clicked", self._show_add_entry)
        header.pack_end(add_button)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.set_content(scroller)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.content.set_margin_top(14)
        self.content.set_margin_bottom(18)
        self.content.set_margin_start(14)
        self.content.set_margin_end(14)
        scroller.set_child(self.content)

        self.day_label = Gtk.Label(xalign=0)
        self.day_label.add_css_class("title-2")
        self.content.append(self.day_label)

        self.bars = {
            "calories": NutrientBar("Calories", "kcal"),
            "protein": NutrientBar("Protein", "g"),
            "carbs": NutrientBar("Carbs", "g"),
            "fat": NutrientBar("Fat", "g"),
        }
        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        summary.add_css_class("card")
        summary.add_css_class("nutrient-summary")
        summary.set_margin_top(2)
        summary.set_margin_bottom(2)
        for bar in self.bars.values():
            summary.append(bar)
        self.content.append(summary)

        self.list = Gtk.ListBox()
        self.list.add_css_class("boxed-list")
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.content.append(self.list)

        self.empty = Adw.StatusPage(
            icon_name=choose_icon(
                "list-add-symbolic",
                "document-new-symbolic",
                "appointment-new-symbolic",
            ),
            title="No food logged",
            description="Tap the plus button to add an entry.",
        )
        self.empty.set_vexpand(True)
        self.content.append(self.empty)

        self.refresh()

    def refresh(self):
        self.day_label.set_label(self._day_title())

        totals = self.store.totals_for(self.selected_day.isoformat())
        for key, bar in self.bars.items():
            bar.set_amount(totals[key], self.store.goals[key])

        while child := self.list.get_first_child():
            self.list.remove(child)

        entries = self.store.entries_for(self.selected_day.isoformat())
        for entry in entries:
            row = EntryRow(entry)
            row.connect("delete-entry", self._delete_entry)
            row.connect("edit-entry", self._edit_entry)
            self.list.append(row)

        self.list.set_visible(bool(entries))
        self.empty.set_visible(not entries)

    def _day_title(self):
        today = date.today()
        if self.selected_day == today:
            return "Today"
        if self.selected_day == today - timedelta(days=1):
            return "Yesterday"
        if self.selected_day == today + timedelta(days=1):
            return "Tomorrow"
        return self.selected_day.strftime("%a, %b %-d")

    def _change_day(self, _button, delta):
        self.selected_day += timedelta(days=delta)
        self.refresh()

    def go_to_day(self, selected_day):
        self.selected_day = selected_day
        self.refresh()

    def _show_add_entry(self, _button):
        AddEntryDialog(self, self.selected_day.isoformat(), self._add_entry)

    def _show_goals(self, _button):
        GoalsDialog(self, self.store, self.refresh)

    def _show_month_overview(self, _button):
        MonthOverviewDialog(self, self.store, self.selected_day, self.go_to_day)

    def _add_entry(self, day, name, calories, protein, carbs, fat):
        self.store.add_entry(day, name, calories, protein, carbs, fat)
        self.refresh()

    def _edit_entry(self, _row, entry_id):
        for entry in self.store.entries_for(self.selected_day.isoformat()):
            if entry.id == entry_id:
                AddEntryDialog(self, self.selected_day.isoformat(), self._update_entry, entry)
                break

    def _update_entry(self, entry_id, day, name, calories, protein, carbs, fat):
        self.store.update_entry(entry_id, day, name, calories, protein, carbs, fat)
        self.refresh()

    def _delete_entry(self, _row, entry_id):
        self.store.delete_entry(entry_id)
        self.refresh()
