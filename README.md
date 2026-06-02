# NomNomus

A small Python GTK 4 / Libadwaita nutrient tracker made for Linux phones.

![Alt Text](./screenshots/Animation.gif)

## Features

- Daily food log
- Editable goal range percentage for month tracking
- Monthly heatmap overview
- Food barcode scanning with an in-app camera preview
- Local SQLite storage in `$XDG_DATA_HOME/nomnomus/data.sqlite3`

## Project layout

- `src/main.py` starts the app directly from a checkout.
- `src/nomnomus/` contains the Python application package.
- `data/` contains desktop integration assets, with folders reserved for icons and services.
- `debian/` is reserved for Debian package metadata.
- `pyproject.toml` contains Python packaging metadata and the `nomnomus` command.
- `screenshots/` contains preview images.

## Installation

### Reccomended installation

To install nomnomus via deb pack see releases and run: 
```sh
sudo apt install ./dist/nomnomus_0.1.0_all.deb
```

### Other installations

To install the `nomnomus` command from a checkout, run manually:

```sh
python3 -m pip install --user -e .
```

On Debian, Ubuntu, or Mobian with apt packages, the dependencies are usually:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-gtk4 \
  gstreamer1.0-tools
```

On Fedora:

```sh
sudo dnf install python3-gobject gtk4 libadwaita python3-gstreamer1 \
  gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugin-gtk4
```

On mingw-w64 (used for testing):
```sh
pacman -S --needed   mingw-w64-ucrt-x86_64-python   mingw-w64-ucrt-x86_64-python-gobject   mingw-w64-ucrt-x86_64-gtk4   mingw-w64-ucrt-x86_64-libadwaita   mingw-w64-ucrt-x86_64-gstreamer   mingw-w64-ucrt-x86_64-gst-plugins-good   mingw-w64-ucrt-x86_64-gst-plugins-bad   mingw-w64-ucrt-x86_64-gst-plugin-gtk mingw-w64-x86_64-libadwaita
```


## Run

Install the GTK and Libadwaita Python bindings for your distro, then run:

```sh
python3 src/main.py
```

You can also launch it with:

```sh
./src/run.sh
```

## Notes

This is intentionally tiny and offline-first. It does not track micronutrients or sync data yet.

Barcode lookup and manual name search use Open Food Facts and need a network
connection. Name search starts after you stop typing for one second. Scanning needs
GStreamer's `zbar`, `autovideosrc`, and `gtk4paintablesink` plugins. The scan screen
also accepts a typed barcode when a camera is unavailable. On DroidMedia phones,
the scanner requests continuous autofocus and the barcode camera scene preset.

In the monthly overview, OK days are counted only from days where you logged food.
The over/under totals compare your consumed monthly totals against the target days
for that month: month-to-date for the current month, or the full month for past months.

To add it to a phone launcher, install the `nomnomus` command and copy
`data/dev.local.NomNomus.desktop` into `~/.local/share/applications/`. Copy
`data/icons/dev.local.NomNomus.svg` into
`~/.local/share/icons/hicolor/scalable/apps/` to install the launcher icon.
The desktop file launches the installed command.

# Resources

[Linuxphone Forum](https://linuxphone.io/)

[Linuxphone Wiki](https://wiki.linuxphone.io/index.php?title=Main_Page)
