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

from .barcodes import BarcodeLookupError, fetch_product
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


def __getattr__(name):
    if name == "AddEntryDialog":
        from .edit_food import AddEntryDialog

        return AddEntryDialog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
