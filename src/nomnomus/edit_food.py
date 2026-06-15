import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk

from .barcodes import BarcodeLookupError, ScannedFood, search_products
from .dialogs import BarcodeScannerDialog, make_adjustment
from .icons import choose_icon, icon_button
from .models import calories_from_macros


SEARCH_LOAD_THRESHOLD = 48
SEARCH_PAGE_SIZE = 8


class AddEntryDialog(Adw.Dialog):
    def __init__(self, parent, day, on_save, entry=None, store=None):
        super().__init__()
        self.day = day
        self.on_save = on_save
        self.entry = entry
        self.store = store
        self.scanned_food = None
        self.search_timeout_id = None
        self.search_generation = 0
        self.last_search_query = None
        self.search_query = None
        self.search_page = 0
        self.search_loading = False
        self.search_has_more = False
        self.search_seen_barcodes = set()
        self.search_result_count = 0
        self.suppress_name_search = False
        self.search_result_selected = False
        self.is_closed = False
        self.amount_basis = None

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

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        top_clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        top_form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        top_form.set_margin_top(18)
        top_form.set_margin_bottom(12)
        top_form.set_margin_start(16)
        top_form.set_margin_end(16)

        self.name = Gtk.Entry(placeholder_text="Food or meal")
        if entry:
            self.name.set_text(entry.name)
        else:
            self.name.connect("changed", self._on_name_changed)
        top_form.append(self.name)

        self.search_status = Gtk.Label(xalign=0, wrap=True)
        self.search_status.add_css_class("caption")
        self.search_status.add_css_class("dim-label")
        self.search_status.set_visible(False)
        top_form.append(self.search_status)

        self.search_results = Gtk.ListBox()
        self.search_results.add_css_class("boxed-list")
        self.search_results.set_selection_mode(Gtk.SelectionMode.NONE)
        self.search_results.set_activate_on_single_click(True)
        self.search_results.connect("row-activated", self._activate_name_search_result)

        self.search_scroller = Gtk.ScrolledWindow()
        self.search_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.search_scroller.set_min_content_height(160)
        self.search_scroller.set_max_content_height(220)
        self.search_scroller.set_child(self.search_results)
        self.search_scroller.set_visible(False)
        self.search_scroller.get_vadjustment().connect(
            "value-changed", self._on_search_results_scrolled
        )
        top_form.append(self.search_scroller)

        self.scan_note = Gtk.Label(xalign=0, wrap=True)
        self.scan_note.add_css_class("caption")
        self.scan_note.add_css_class("dim-label")
        self.scan_note.set_visible(False)
        top_form.append(self.scan_note)

        top_clamp.set_child(top_form)
        content.append(top_clamp)

        bottom_clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        form.set_margin_top(2)
        form.set_margin_bottom(24)
        form.set_margin_start(16)
        form.set_margin_end(16)

        self.amount = self._spin("Amount eaten (g)", 0, 10000, 1)
        self.amount.spin.connect("value-changed", self._update_amount)
        form.append(self.amount)

        self.protein = self._spin("Protein (g)", 0, 500, 1)
        self.carbs = self._spin("Carbs (g)", 0, 800, 1)
        self.fat = self._spin("Fat (g)", 0, 300, 1)
        self.calories = self._spin("Calories", 0, 10000, 1)
        self.calories.spin.set_sensitive(False)

        for row in (self.protein, self.carbs, self.fat, self.calories):
            form.append(row)

        if entry:
            if entry.grams > 0:
                self.amount_basis = {
                    "grams": entry.grams,
                    "protein": entry.protein,
                    "carbs": entry.carbs,
                    "fat": entry.fat,
                }
            self.amount.spin.set_value(entry.grams)
            self.protein.spin.set_value(entry.protein)
            self.carbs.spin.set_value(entry.carbs)
            self.fat.spin.set_value(entry.fat)

        for row in (self.protein, self.carbs, self.fat):
            row.spin.connect("value-changed", self._update_calories)
        self._update_calories()

        bottom_clamp.set_child(form)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(bottom_clamp)
        content.append(scroller)

        toolbar_view.set_content(content)
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

    def _apply_food(self, food, note, clear_search=True):
        self.scanned_food = food
        self.amount_basis = None
        self.suppress_name_search = True
        self.name.set_text(food.name)
        self.suppress_name_search = False
        self.amount.spin.set_value(food.basis_quantity)
        self._update_amount()
        self.scan_note.set_label(note)
        self.scan_note.set_visible(True)
        if clear_search:
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
        self.search_query = query
        self.search_page = 0
        self.search_loading = True
        self.search_has_more = False
        self.search_result_selected = False
        self.search_seen_barcodes = set()
        self.search_result_count = 0
        self._append_recipe_search_results(query)
        thread = threading.Thread(
            target=self._fetch_name_search,
            args=(query, generation, 1),
            daemon=True,
        )
        thread.start()
        return GLib.SOURCE_REMOVE

    def _fetch_name_search(self, query, generation, page):
        try:
            foods = search_products(query, page_size=SEARCH_PAGE_SIZE, page=page)
        except BarcodeLookupError as error:
            GLib.idle_add(self._name_search_failed, generation, page, str(error))
        else:
            GLib.idle_add(self._name_search_succeeded, generation, query, page, foods)

    def _name_search_succeeded(self, generation, query, page, foods):
        if self.is_closed or generation != self.search_generation:
            return GLib.SOURCE_REMOVE

        self.search_loading = False

        added = 0
        for food in foods:
            if food.barcode in self.search_seen_barcodes:
                continue
            self.search_seen_barcodes.add(food.barcode)
            self._append_search_result(food)
            added += 1

        self.search_query = query
        self.search_page = page
        self.search_has_more = len(foods) >= SEARCH_PAGE_SIZE

        if page == 1 and not added and self.search_result_count == 0:
            self.search_status.set_label("No Open Food Facts matches found.")
            self.search_status.set_visible(True)
            return GLib.SOURCE_REMOVE

        if self.search_has_more:
            self.search_status.set_label("Select a matching product. Scroll for more.")
        else:
            self.search_status.set_label("Select a matching product:")
        self.search_status.set_visible(True)
        self.search_scroller.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _name_search_failed(self, generation, page, message):
        if self.is_closed or generation != self.search_generation:
            return GLib.SOURCE_REMOVE
        self.search_loading = False
        self.search_has_more = False
        if page == 1 and self.search_result_count == 0:
            self._clear_search_results()
        if page == 1 and self.search_result_count:
            self.search_status.set_label("Showing saved recipes. Open Food Facts failed.")
        else:
            self.search_status.set_label(message)
        self.search_status.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _append_recipe_search_results(self, query):
        if not self.store:
            return
        for recipe in self.store.recipes_matching(query):
            food = self._food_from_recipe(recipe)
            self.search_seen_barcodes.add(food.barcode)
            self._append_search_result(food)
        if self.search_result_count:
            self.search_status.set_label("Select a saved recipe or Open Food Facts match:")
            self.search_status.set_visible(True)
            self.search_scroller.set_visible(True)

    def _food_from_recipe(self, recipe):
        basis_quantity = recipe.grams if recipe.grams > 0 else 1
        factor = 100 / basis_quantity
        return ScannedFood(
            barcode=f"recipe:{recipe.id}",
            name=recipe.name,
            protein=recipe.protein,
            carbs=recipe.carbs,
            fat=recipe.fat,
            basis=f"{basis_quantity:g} g recipe",
            basis_quantity=basis_quantity,
            brand="Saved recipe",
            protein_100g=recipe.protein * factor,
            carbs_100g=recipe.carbs * factor,
            fat_100g=recipe.fat * factor,
            source="recipe",
        )

    def _append_search_result(self, food):
        result = Gtk.ListBoxRow()
        result.food = food
        result.set_activatable(True)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(10)
        row.set_margin_bottom(10)
        row.set_margin_start(12)
        row.set_margin_end(12)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.set_hexpand(True)

        name = Gtk.Label(label=food.name, xalign=0)
        name.add_css_class("body")
        name.set_wrap(True)
        labels.append(name)

        metadata = self._food_metadata(food)
        if metadata:
            meta_label = Gtk.Label(label=metadata, xalign=0)
            meta_label.add_css_class("caption")
            meta_label.add_css_class("dim-label")
            meta_label.set_wrap(True)
            labels.append(meta_label)

        nutrition = Gtk.Label(label=self._food_nutrition(food), xalign=0)
        nutrition.add_css_class("caption")
        nutrition.add_css_class("dim-label")
        nutrition.set_wrap(True)
        labels.append(nutrition)

        source_icon = Gtk.Image.new_from_icon_name(
            self._food_source_icon(food)
        )
        source_icon.add_css_class("dim-label")
        source_icon.set_tooltip_text(self._food_source_tooltip(food))
        source_icon.set_valign(Gtk.Align.START)
        source_icon.set_margin_top(2)

        row.append(labels)
        row.append(source_icon)
        result.set_child(row)
        self.search_results.append(result)
        self.search_result_count += 1

    def _activate_name_search_result(self, _listbox, row):
        GLib.idle_add(self._select_name_search_result, row, row.food)

    def _food_metadata(self, food):
        if food.source == "recipe":
            return "Saved recipe"
        if food.brand and food.brand != food.name:
            return food.brand
        return ""

    def _food_nutrition(self, food):
        calories = calories_from_macros(food.protein_100g, food.carbs_100g, food.fat_100g)
        return (
            f"{calories:.0f} kcal | "
            f"P {food.protein_100g:g}g  C {food.carbs_100g:g}g  "
            f"F {food.fat_100g:g}g per 100g"
        )

    def _food_source_icon(self, food):
        if food.source == "recipe":
            return choose_icon(
                "starred-symbolic",
                "emblem-favorite-symbolic",
                "non-starred-symbolic",
            )
        return choose_icon(
            "globe-symbolic",
            "web-browser-symbolic",
            "network-workgroup-symbolic",
            "applications-internet-symbolic",
        )

    def _food_source_tooltip(self, food):
        return "Saved recipe" if food.source == "recipe" else "Open Food Facts"

    def _on_search_results_scrolled(self, adjustment):
        if (
            self.is_closed
            or not self.search_scroller.get_visible()
            or not self.search_query
            or not self.search_has_more
            or self.search_loading
        ):
            return

        visible_bottom = adjustment.get_value() + adjustment.get_page_size()
        if visible_bottom >= adjustment.get_upper() - SEARCH_LOAD_THRESHOLD:
            self._load_next_search_page()

    def _load_next_search_page(self):
        self.search_loading = True
        self.search_status.set_label("Loading more Open Food Facts matches...")
        thread = threading.Thread(
            target=self._fetch_name_search,
            args=(self.search_query, self.search_generation, self.search_page + 1),
            daemon=True,
        )
        thread.start()

    def _select_name_search_result(self, _row, food):
        if self.search_result_selected:
            return GLib.SOURCE_REMOVE
        self.search_result_selected = True
        self._cancel_name_search()
        self.search_generation += 1
        self.last_search_query = food.name
        self._apply_food(
            food,
            f"Selected {food.name}. Nutrition is calculated from {food.basis}.",
            clear_search=False,
        )
        self.search_scroller.set_visible(False)
        self.search_status.set_visible(False)
        GLib.timeout_add(100, self._clear_search_results)
        return GLib.SOURCE_REMOVE

    def _clear_search_results(self):
        while child := self.search_results.get_first_child():
            self.search_results.remove(child)
        self.search_scroller.set_visible(False)
        self.search_page = 0
        self.search_query = None
        self.search_loading = False
        self.search_has_more = False
        self.search_seen_barcodes = set()
        self.search_result_count = 0

    def _cancel_name_search(self):
        if self.search_timeout_id:
            GLib.source_remove(self.search_timeout_id)
            self.search_timeout_id = None

    def _on_closed(self, _dialog):
        self.is_closed = True
        self.search_generation += 1
        self._cancel_name_search()

    def _update_amount(self, _spin=None):
        if self.scanned_food:
            protein, carbs, fat = self.scanned_food.macros_for_amount(
                self.amount.spin.get_value()
            )
            self.protein.spin.set_value(protein)
            self.carbs.spin.set_value(carbs)
            self.fat.spin.set_value(fat)
            return

        if not self.amount_basis:
            return

        factor = self.amount.spin.get_value() / self.amount_basis["grams"]
        self.protein.spin.set_value(self.amount_basis["protein"] * factor)
        self.carbs.spin.set_value(self.amount_basis["carbs"] * factor)
        self.fat.spin.set_value(self.amount_basis["fat"] * factor)

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
            self.amount.spin.get_value(),
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
