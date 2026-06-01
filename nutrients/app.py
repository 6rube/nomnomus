import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from . import APP_ID, APP_NAME
from .styles import load_css
from .window import Window


class NutrientTracker(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)

    def do_activate(self):
        load_css()
        window = self.props.active_window
        if window is None:
            window = Window(self)
        window.present()


def main():
    app = NutrientTracker()
    return app.run()
