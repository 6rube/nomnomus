import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")

from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402,F401

from .icons import choose_icon


class NutrientBar(Gtk.Box):
    def __init__(self, label, unit):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.unit = unit

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.title = Gtk.Label(label=label, xalign=0)
        self.value = Gtk.Label(xalign=1)
        self.title.add_css_class("caption-heading")
        self.value.add_css_class("caption")
        row.append(self.title)
        row.append(self.value)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)

        self.append(row)
        self.append(self.progress)

    def set_amount(self, amount, goal):
        fraction = min(amount / goal, 1.0) if goal else 0.0
        self.progress.set_fraction(fraction)
        self.value.set_label(f"{amount:.0f} / {goal:.0f} {self.unit}")


class EntryRow(Gtk.ListBoxRow):
    __gsignals__ = {
        "delete-entry": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "edit-entry": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, entry):
        super().__init__()
        self.entry = entry

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(8)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=entry.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("body")
        macros = Gtk.Label(
            label=(
                f"{entry.calories:.0f} kcal  "
                f"P {entry.protein:.0f}g  C {entry.carbs:.0f}g  F {entry.fat:.0f}g"
            ),
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        macros.add_css_class("caption")
        macros.add_css_class("dim-label")
        text.append(title)
        text.append(macros)
        text.set_hexpand(True)

        edit_button = Gtk.Button()
        edit_button.set_icon_name(
            choose_icon("edit-symbolic", "document-edit-symbolic", "document-edit")
        )
        edit_button.add_css_class("flat")
        edit_button.set_tooltip_text("Edit entry")
        edit_button.connect("clicked", self._on_edit_clicked)

        delete_button = Gtk.Button(
            icon_name=choose_icon("user-trash-symbolic", "edit-delete-symbolic")
        )
        delete_button.add_css_class("flat")
        delete_button.set_tooltip_text("Delete entry")
        delete_button.connect("clicked", self._on_delete_clicked)

        box.append(text)
        box.append(edit_button)
        box.append(delete_button)
        self.set_child(box)
        self.set_activatable(True)
        self.connect("activate", self._on_activate)

    def _on_edit_clicked(self, _button):
        self.emit("edit-entry", self.entry.id)

    def _on_delete_clicked(self, _button):
        self.emit("delete-entry", self.entry.id)

    def _on_activate(self, _row):
        self.emit("edit-entry", self.entry.id)
