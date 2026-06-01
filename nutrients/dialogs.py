import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except (ImportError, ValueError):
    Gst = None

from .barcodes import BarcodeLookupError, fetch_product, search_products
from .icons import icon_button
from .models import DEFAULT_SETTINGS, calories_from_macros


def make_adjustment(value, lower, upper, step, page):
    return Gtk.Adjustment(
        value=value,
        lower=lower,
        upper=upper,
        step_increment=step,
        page_increment=page,
        page_size=0,
    )


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


class BarcodeScannerDialog(Adw.Dialog):
    def __init__(self, parent, on_scanned):
        super().__init__()
        self.on_scanned = on_scanned
        self.pipeline = None
        self.camera_bus = None
        self.camera_bus_handler = None
        self.camera_pipelines = []
        self.camera_pipeline_index = 0
        self.lookup_in_progress = False
        self.is_closed = False

        self.set_title("Scan Barcode")
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

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        overlay = Gtk.Overlay()
        overlay.set_vexpand(True)
        overlay.set_size_request(-1, 360)
        overlay.add_css_class("scanner-preview")

        self.preview = Gtk.Picture()
        self.preview.set_content_fit(Gtk.ContentFit.COVER)
        self.preview.set_hexpand(True)
        self.preview.set_vexpand(True)
        overlay.set_child(self.preview)

        guide = Gtk.Box()
        guide.set_size_request(240, 150)
        guide.set_halign(Gtk.Align.CENTER)
        guide.set_valign(Gtk.Align.CENTER)
        guide.add_css_class("scanner-guide")
        overlay.add_overlay(guide)
        content.append(overlay)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(
            label="Point the camera at a food barcode.",
            xalign=0,
            wrap=True,
            hexpand=True,
        )
        self.status.add_css_class("caption")
        status_row.append(self.spinner)
        status_row.append(self.status)
        content.append(status_row)

        manual_label = Gtk.Label(label="Or enter a barcode number", xalign=0)
        manual_label.add_css_class("caption-heading")
        content.append(manual_label)

        manual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.barcode = Gtk.Entry(placeholder_text="Barcode number", hexpand=True)
        self.barcode.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.barcode.connect("activate", self._lookup_entered_barcode)
        manual_row.append(self.barcode)

        self.lookup_button = Gtk.Button(label="Look Up")
        self.lookup_button.connect("clicked", self._lookup_entered_barcode)
        manual_row.append(self.lookup_button)
        content.append(manual_row)

        toolbar_view.set_content(content)
        self.set_child(toolbar_view)
        self.connect("closed", self._on_closed)
        self.present(parent)
        self._start_camera()

    def _start_camera(self):
        if Gst is None:
            self.status.set_label("Camera scanning is not installed. Enter a barcode below.")
            return

        Gst.init(None)
        self.camera_pipelines = self._camera_pipeline_descriptions()
        self.camera_pipeline_index = 0
        self._start_next_camera()

    def _camera_pipeline_descriptions(self):
        branches = (
            " ! tee name=stream "
            "stream. ! queue leaky=downstream max-size-buffers=1 "
            "max-size-bytes=0 max-size-time=0 "
            "! gtk4paintablesink name=preview sync=false "
            "stream. ! queue leaky=downstream max-size-buffers=1 "
            "max-size-bytes=0 max-size-time=0 "
            "! videorate drop-only=true max-rate=12 ! videoscale "
            "! video/x-raw,width=960,height=540 "
            "! zbar name=barcode message=true cache=true ! fakesink sync=false"
        )
        pipelines = []

        if Path("/dev/binder").exists() and Gst.ElementFactory.find("droidcamsrc"):
            pipelines.append(
                "droidcamsrc name=camera focus-mode=continuous-normal scene-mode=barcode "
                "camera.vfsrc ! video/x-raw,width=1280,height=720,framerate=30/1"
                + branches
            )
        pipelines.append(
            "autovideosrc ! videoconvert ! videoscale "
            "! video/x-raw,width=1280,height=720,framerate=30/1" + branches
        )
        return pipelines

    def _start_next_camera(self, last_error=None):
        if self.is_closed:
            return

        if self.camera_pipeline_index >= len(self.camera_pipelines):
            message = f" ({last_error})" if last_error else ""
            self.status.set_label(f"Camera unavailable{message}. Enter a barcode below.")
            return

        description = self.camera_pipelines[self.camera_pipeline_index]
        self.camera_pipeline_index += 1
        try:
            self.pipeline = Gst.parse_launch(description)
            sink = self.pipeline.get_by_name("preview")
            self.preview.set_paintable(sink.get_property("paintable"))

            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            self.camera_bus = bus
            self.camera_bus_handler = bus.connect("message", self._on_bus_message)
            result = self.pipeline.set_state(Gst.State.PLAYING)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("camera pipeline could not start")
        except (GLib.Error, RuntimeError) as error:
            self._stop_camera()
            self._start_next_camera(error)

    def _on_bus_message(self, bus, message):
        if bus != self.camera_bus:
            return

        if message.type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure and structure.get_name() == "barcode":
                self._lookup(structure.get_string("symbol"))
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._stop_camera()
            self._start_next_camera(error.message)

    def _lookup_entered_barcode(self, _widget):
        self._lookup(self.barcode.get_text())

    def _lookup(self, barcode):
        if self.lookup_in_progress:
            return

        barcode = str(barcode).strip()
        self.barcode.set_text(barcode)
        self.lookup_in_progress = True
        self.barcode.set_sensitive(False)
        self.lookup_button.set_sensitive(False)
        self.spinner.start()
        self.status.set_label(f"Looking up {barcode}...")
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)

        thread = threading.Thread(target=self._fetch_product, args=(barcode,), daemon=True)
        thread.start()

    def _fetch_product(self, barcode):
        try:
            food = fetch_product(barcode)
        except BarcodeLookupError as error:
            GLib.idle_add(self._lookup_failed, str(error))
        else:
            GLib.idle_add(self._lookup_succeeded, food)

    def _lookup_succeeded(self, food):
        if self.is_closed:
            return GLib.SOURCE_REMOVE
        self._stop_camera()
        self.on_scanned(food)
        self.close()
        return GLib.SOURCE_REMOVE

    def _lookup_failed(self, message):
        if self.is_closed:
            return GLib.SOURCE_REMOVE
        self.lookup_in_progress = False
        self.barcode.set_sensitive(True)
        self.lookup_button.set_sensitive(True)
        self.spinner.stop()
        self.status.set_label(message)
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)
        return GLib.SOURCE_REMOVE

    def _stop_camera(self):
        if self.camera_bus:
            if self.camera_bus_handler:
                self.camera_bus.disconnect(self.camera_bus_handler)
            self.camera_bus.remove_signal_watch()
            self.camera_bus = None
            self.camera_bus_handler = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        self.preview.set_paintable(None)

    def _on_closed(self, _dialog):
        self.is_closed = True
        self._stop_camera()


class GoalsDialog(Adw.Dialog):
    def __init__(self, parent, store, on_save):
        super().__init__()
        self.store = store
        self.on_save = on_save

        self.set_title("Daily Goals")
        self.set_content_width(420)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda _button: self.close())
        header.pack_start(close)

        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_end(save)

        clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        form.set_margin_top(18)
        form.set_margin_bottom(24)
        form.set_margin_start(16)
        form.set_margin_end(16)

        self.fields = {}
        labels = (
            ("protein", "Protein (g)"),
            ("carbs", "Carbs (g)"),
            ("fat", "Fat (g)"),
            ("calories", "Calories"),
        )
        for key, title in labels:
            row = Adw.ActionRow(title=title)
            spin = Gtk.SpinButton()
            spin.set_adjustment(make_adjustment(self.store.goals[key], 0, 10000, 1, 10))
            spin.set_numeric(True)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_width_chars(5)
            if key == "calories":
                spin.set_sensitive(False)
            row.add_suffix(spin)
            form.append(row)
            self.fields[key] = spin

        for key in ("protein", "carbs", "fat"):
            self.fields[key].connect("value-changed", self._update_calories)
        self._update_calories()

        range_row = Adw.ActionRow(
            title="Goal range",
            subtitle="Daily overview is OK when every goal is within this percent.",
        )
        self.range_percent = Gtk.SpinButton()
        self.range_percent.set_adjustment(
            make_adjustment(
                self.store.settings.get("range_percent", DEFAULT_SETTINGS["range_percent"]),
                0,
                100,
                1,
                5,
            )
        )
        self.range_percent.set_numeric(True)
        self.range_percent.set_valign(Gtk.Align.CENTER)
        self.range_percent.set_width_chars(4)
        range_row.add_suffix(self.range_percent)
        range_row.add_suffix(Gtk.Label(label="%"))
        form.append(range_row)

        clamp.set_child(form)
        toolbar_view.set_content(clamp)
        self.set_child(toolbar_view)
        self.present(parent)

    def _save(self, _button):
        self._update_calories()
        for key, spin in self.fields.items():
            self.store.goals[key] = spin.get_value()
        self.store.settings["range_percent"] = self.range_percent.get_value()
        self.store.save()
        self.on_save()
        self.close()

    def _update_calories(self, _spin=None):
        self.fields["calories"].set_value(
            calories_from_macros(
                self.fields["protein"].get_value(),
                self.fields["carbs"].get_value(),
                self.fields["fat"].get_value(),
            )
        )
