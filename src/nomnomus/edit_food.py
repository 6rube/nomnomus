import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk

from .barcodes import BarcodeLookupError, search_products
from .dialogs import BarcodeScannerDialog, make_adjustment
from .icons import icon_button
from .models import calories_from_macros


class AddEntryDialog(Adw.Dialog):
    def __init__(self, parent, day, on_save, entry=None):
        super().__init__()
        self.day = day
        self.on_save = on_save
        self.entry = entry
        self.scanned_food = None
        self.search_timeout_id = None
        self.search_generation = 0
        self.last_search_query = None
        self.suppress_name_search = False
        self.search_result_selected = False
        self.is_closed = False

        self.set_title("Edit Food" if entry else "Add Food")
        self.set_content_width(420)
        if hasattr(self, "set_content_height"):
            self.set_content_height(620)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: self.close())
        header.pack_start(cancel)

        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_end(save)

        if not entry:
            scan = icon_button("camera-photo-symbolic", "Scan")
            scan.set_tooltip_text("Scan food barcode")
            scan.connect("clicked", self._show_scanner)
            header.pack_end(scan)

        clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        form.set_margin_top(18)
        form.set_margin_bottom(24)
        form.set_margin_start(16)
        form.set_margin_end(16)

        self.name = Gtk.Entry(placeholder_text="Food or meal")
        if entry:
            self.name.set_text(entry.name)
        else:
            self.name.connect("changed", self._on_name_changed)
        form.append(self.name)

        self.search_status = Gtk.Label(xalign=0, wrap=True)
        self.search_status.add_css_class("caption")
        self.search_status.add_css_class("dim-label")
        self.search_status.set_visible(False)
        form.append(self.search_status)

        self.search_results = Gtk.ListBox()
        self.search_results.add_css_class("boxed-list")
        self.search_results.set_selection_mode(Gtk.SelectionMode.NONE)
        self.search_results.set_size_request(-1, 180)
        self.search_results.set_visible(False)
        form.append(self.search_results)

        self.scan_note = Gtk.Label(xalign=0, wrap=True)
        self.scan_note.add_css_class("caption")
        self.scan_note.add_css_class("dim-label")
        self.scan_note.set_visible(False)
        form.append(self.scan_note)

        self.amount = self._spin("Amount eaten (g)", 0, 10000, 1)
        self.amount.set_visible(False)
        self.amount.spin.connect("value-changed", self._update_scanned_amount)
        form.append(self.amount)

        self.protein = self._spin("Protein (g)", 0, 500, 1)
        self.carbs = self._spin("Carbs (g)", 0, 800, 1)
        self.fat = self._spin("Fat (g)", 0, 300, 1)
        self.calories = self._spin("Calories", 0, 10000, 1)
        self.calories.spin.set_sensitive(False)

        for row in (self.protein, self.carbs, self.fat, self.calories):
            form.append(row)

        if entry:
            self.protein.spin.set_value(entry.protein)
            self.carbs.spin.set_value(entry.carbs)
            self.fat.spin.set_value(entry.fat)

        for row in (self.protein, self.carbs, self.fat):
            row.spin.connect("value-changed", self._update_calories)
        self._update_calories()

        clamp.set_child(form)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(clamp)
        toolbar_view.set_content(scroller)
        self.set_child(toolbar_view)
        self.connect("closed", self._on_closed)
        self.present(parent)

    def _show_scanner(self, _button):
        BarcodeScannerDialog(self, self._apply_scanned_food)

    def _apply_scanned_food(self, food):
        self._apply_food(
            food,
            f"Scanned {food.barcode}. Nutrition is calculated from {food.basis}.",
        )

    def _apply_food(self, food, note):
        self.scanned_food = food
        self.suppress_name_search = True
        self.name.set_text(food.name)
        self.suppress_name_search = False
        self.amount.set_visible(True)
        self.amount.spin.set_value(food.basis_quantity)
        self._update_scanned_amount()
        self.scan_note.set_label(note)
        self.scan_note.set_visible(True)
        self._clear_search_results()
        self.search_status.set_visible(False)

    def _on_name_changed(self, _entry):
        if self.suppress_name_search:
            return

        self._cancel_name_search()
        self.search_generation += 1
        query = self.name.get_text().strip()
        if len(query) < 3:
            self.search_status.set_visible(False)
            self._clear_search_results()
            return
        if query == self.last_search_query:
            return

        self.search_status.set_label("Waiting to search Open Food Facts...")
        self.search_status.set_visible(True)
        self._clear_search_results()
        self.search_timeout_id = GLib.timeout_add_seconds(
            2, self._start_name_search, query, self.search_generation
        )

    def _start_name_search(self, query, generation):
        self.search_timeout_id = None
        if self.is_closed or generation != self.search_generation:
            return GLib.SOURCE_REMOVE

        self.last_search_query = query
        self.search_status.set_label("Searching Open Food Facts...")
        thread = threading.Thread(
            target=self._fetch_name_search,
            args=(query, generation),
            daemon=True,
        )
        thread.start()
        return GLib.SOURCE_REMOVE

    def _fetch_name_search(self, query, generation):
        try:
            foods = search_products(query)
        except BarcodeLookupError as error:
            GLib.idle_add(self._name_search_failed, generation, str(error))
        else:
            GLib.idle_add(self._name_search_succeeded, generation, foods)

    def _name_search_succeeded(self, generation, foods):
        if self.is_closed or generation != self.search_generation:
            return GLib.SOURCE_REMOVE

        self._clear_search_results()
        self.search_result_selected = False
        if not foods:
            self.search_status.set_label("No Open Food Facts matches found.")
            self.search_status.set_visible(True)
            return GLib.SOURCE_REMOVE

        self.search_status.set_label("Select a matching product:")
        self.search_status.set_visible(True)
        for food in foods:
            result = Gtk.Button()
            result.add_css_class("flat")
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = Gtk.Label(label=food.name, xalign=0)
            name.add_css_class("body")
            details = Gtk.Label(label=f"{food.basis} | {food.barcode}", xalign=0)
            details.add_css_class("caption")
            details.add_css_class("dim-label")
            labels.append(name)
            labels.append(details)
            result.set_child(labels)
            tap = Gtk.GestureClick()
            tap.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            tap.connect("pressed", self._tap_name_search_result, food)
            result.add_controller(tap)
            result.connect("clicked", self._select_name_search_result, food)
            self.search_results.append(result)
        self.search_results.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _name_search_failed(self, generation, message):
        if self.is_closed or generation != self.search_generation:
            return GLib.SOURCE_REMOVE
        self._clear_search_results()
        self.search_status.set_label(message)
        self.search_status.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _tap_name_search_result(self, _gesture, _press_count, _x, _y, food):
        self._select_name_search_result(None, food)

    def _select_name_search_result(self, _row, food):
        if self.search_result_selected:
            return
        self.search_result_selected = True
        self._cancel_name_search()
        self.search_generation += 1
        self.last_search_query = food.name
        self._apply_food(
            food,
            f"Selected {food.name}. Nutrition is calculated from {food.basis}.",
        )

    def _clear_search_results(self):
        while child := self.search_results.get_first_child():
            self.search_results.remove(child)
        self.search_results.set_visible(False)

    def _cancel_name_search(self):
        if self.search_timeout_id:
            GLib.source_remove(self.search_timeout_id)
            self.search_timeout_id = None

    def _on_closed(self, _dialog):
        self.is_closed = True
        self.search_generation += 1
        self._cancel_name_search()

    def _update_scanned_amount(self, _spin=None):
        if not self.scanned_food:
            return

        protein, carbs, fat = self.scanned_food.macros_for_amount(
            self.amount.spin.get_value()
        )
        self.protein.spin.set_value(protein)
        self.carbs.spin.set_value(carbs)
        self.fat.spin.set_value(fat)

    def _spin(self, title, lower, upper, step):
        row = Adw.ActionRow(title=title)
        spin = Gtk.SpinButton()
        spin.set_adjustment(make_adjustment(0, lower, upper, step, step * 10))
        spin.set_numeric(True)
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_width_chars(5)
        row.add_suffix(spin)
        row.spin = spin
        return row

    def _save(self, _button):
        values = (
            self.day,
            self.name.get_text(),
            self.calories.spin.get_value(),
            self.protein.spin.get_value(),
            self.carbs.spin.get_value(),
            self.fat.spin.get_value(),
        )
        if self.entry:
            self.on_save(self.entry.id, *values)
        else:
            self.on_save(*values)
        self.close()

    def _update_calories(self, _spin=None):
        self.calories.spin.set_value(
            calories_from_macros(
                self.protein.spin.get_value(),
                self.carbs.spin.get_value(),
                self.fat.spin.get_value(),
            )
        )
