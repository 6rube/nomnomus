import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # noqa: E402
except (ImportError, ValueError):
    Gst = None

from .barcodes import BarcodeLookupError, fetch_product
from .icons import choose_icon
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

        self.set_title("Edit Food" if entry else "Add Food")
        self.set_content_width(420)

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
            scan = Gtk.Button(
                icon_name=choose_icon("qr-code-symbolic", "camera-photo-symbolic")
            )
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
        form.append(self.name)

        self.scan_note = Gtk.Label(xalign=0, wrap=True)
        self.scan_note.add_css_class("caption")
        self.scan_note.add_css_class("dim-label")
        self.scan_note.set_visible(False)
        form.append(self.scan_note)

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
        toolbar_view.set_content(clamp)
        self.set_child(toolbar_view)
        self.present(parent)

    def _show_scanner(self, _button):
        BarcodeScannerDialog(self, self._apply_scanned_food)

    def _apply_scanned_food(self, food):
        self.name.set_text(food.name)
        self.protein.spin.set_value(food.protein)
        self.carbs.spin.set_value(food.carbs)
        self.fat.spin.set_value(food.fat)
        self.scan_note.set_label(
            f"Scanned {food.barcode}. Loaded values for {food.basis}; "
            "adjust them to match the amount eaten."
        )
        self.scan_note.set_visible(True)

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

        try:
            Gst.init(None)
            self.pipeline = Gst.parse_launch(
                "autovideosrc ! videoconvert ! "
                "zbar name=barcode message=true cache=true ! videoconvert ! "
                "gtk4paintablesink name=preview"
            )
            sink = self.pipeline.get_by_name("preview")
            self.preview.set_paintable(sink.get_property("paintable"))

            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)
            result = self.pipeline.set_state(Gst.State.PLAYING)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("camera pipeline could not start")
        except (GLib.Error, RuntimeError) as error:
            self._stop_camera()
            self.status.set_label(f"Camera unavailable ({error}). Enter a barcode below.")

    def _on_bus_message(self, _bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure and structure.get_name() == "barcode":
                self._lookup(structure.get_string("symbol"))
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._stop_camera()
            self.status.set_label(f"Camera unavailable ({error.message}). Enter a barcode below.")

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
