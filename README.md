# Nutrients

A small Python GTK 4 / Libadwaita nutrient tracker made for narrow Linux phone screens.

## Features

- Daily food log
- Calories, protein, carbs, and fat totals
- Editable daily goals
- Editable goal range percentage for month tracking
- Monthly heatmap overview with OK days and over/under totals
- Previous and next day navigation
- Food barcode scanning with an in-app camera preview
- Local JSON storage in `$XDG_DATA_HOME/nutrient-tracker/data.json`

## Project layout

- `main.py` starts the app.
- `nutrients/app.py` wires up the Libadwaita application.
- `nutrients/window.py` contains the main phone-sized window.
- `nutrients/dialogs.py` contains the add-food and goal dialogs.
- `nutrients/overview.py` contains the monthly heatmap.
- `nutrients/analytics.py` calculates day and month stats.
- `nutrients/widgets.py` contains reusable UI rows and progress bars.
- `nutrients/barcodes.py` looks up scanned products in Open Food Facts.
- `nutrients/store.py` handles local JSON persistence.
- `nutrients/models.py` contains the data model and default goals.

## Run

Install the GTK and Libadwaita Python bindings for your distro, then run:

```sh
python3 main.py
```

You can also launch it with:

```sh
./run.sh
```

On Debian, Ubuntu, or Mobian with apt packages, the dependencies are usually:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-bad gstreamer1.0-gtk4 gstreamer1.0-tools
```

On Fedora:

```sh
sudo dnf install python3-gobject gtk4 libadwaita python3-gstreamer1 \
  gstreamer1-plugins-bad-free gstreamer1-plugin-gtk4
```

## Notes

This is intentionally tiny and offline-first. It does not track micronutrients or sync data yet.

Barcode lookup uses Open Food Facts and needs a network connection. Scanning needs
GStreamer's `zbar`, `autovideosrc`, and `gtk4paintablesink` plugins. The scan screen
also accepts a typed barcode when a camera is unavailable.

In the monthly overview, OK days are counted only from days where you logged food.
The over/under totals compare your consumed monthly totals against the target days
for that month: month-to-date for the current month, or the full month for past months.

To add it to a phone launcher, copy `dev.local.NutrientTracker.desktop` into
`~/.local/share/applications/`. The included file points at this workspace path.
