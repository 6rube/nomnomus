import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402


def icon_button(icon_name, fallback_label):
    button = Gtk.Button()
    display = Gdk.Display.get_default()
    if display and Gtk.IconTheme.get_for_display(display).has_icon(icon_name):
        button.set_child(Gtk.Image.new_from_icon_name(icon_name))
    else:
        button.set_label(fallback_label)
    return button


def choose_icon(*names):
    display = Gdk.Display.get_default()
    if display is None:
        return names[-1]

    theme = Gtk.IconTheme.get_for_display(display)
    for name in names:
        if theme.has_icon(name):
            return name
    return names[-1]
