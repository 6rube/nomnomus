import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402


CSS = """
.heat-day {
  border-radius: 5px;
  min-height: 28px;
  padding: 0;
  font-weight: 700;
}

.compact-totals {
  padding: 8px;
  border-radius: 8px;
  background: alpha(currentColor, 0.06);
}

.scanner-preview {
  border-radius: 10px;
  background: #151515;
}

.scanner-guide {
  border: 3px solid alpha(#ffffff, 0.85);
  border-radius: 10px;
}

.heat-ok {
  background: #2ec27e;
  color: #102016;
}

.heat-future {
  background: alpha(currentColor, 0.08);
  color: alpha(currentColor, 0.40);
}

.heat-warm {
  background: #f6d32d;
  color: #2d2600;
}

.heat-hot {
  background: #ff7800;
  color: #2d1200;
}

.heat-very-hot {
  background: #e01b24;
  color: #ffffff;
}

.heat-max {
  background: #c01c28;
  color: #ffffff;
}
"""


def load_css():
    display = Gdk.Display.get_default()
    if display is None:
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
