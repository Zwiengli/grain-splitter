# Grain Splitter

English | [简体中文](README.zh-CN.md)

[License](LICENSE)

Grain Splitter is a desktop tool for detecting and splitting large film scan sheets, including Hasselblad `FFF` workflows. It is built with Python and Tkinter, and is designed for high-resolution scans that need both automatic detection and manual correction.

## Highlights

- Directly opens `FFF`, `TIFF`, `TIF`, `JPG`, `PNG`, `BMP`, and `WEBP` files.
- Uses asynchronous first-open loading and a low-resolution preview path for very large scans.
- Automatically detects strips, frame boundaries, and scan orientation.
- Supports zoom, pan, preview navigation, manual guide edits, and box-level edits after rotation.
- Supports multi-image browsing, `Export Current`, and `Export All`.
- Lets users adjust `JPEG`, `PNG`, and `TIFF` export compression settings.
- Includes built-in UI languages: English, Simplified Chinese, and German.

## Supported Workflows

### Input Formats

- `FFF`
- `TIFF` / `TIF`
- `JPG` / `JPEG`
- `PNG`
- `BMP`
- `WEBP`

### Output Formats

- Original format when possible
- `JPG`
- `PNG`
- `TIFF`

## Documentation

- [Documentation Index](docs/README.md)
- [Installation Guide](docs/INSTALLATION.md)
- [ART User Commands Guide](docs/ART_USERCOMMANDS.md)

## Requirements

- Python 3.10 or newer is recommended.
- `tkinter` is included in most Windows and macOS Python installers.
- On Linux, you may need to install the system Tk package separately before running the app.

## Repository Layout

```text
.
├── app/          # GUI, preview canvas, settings, and UI logic
├── core/         # Image loading, detection, export, and shared constants
├── docs/         # User-facing documentation
├── i18n/         # UI language files
├── config/       # Default settings and local user settings
├── main.py       # Main entry point
└── neg_splitter.py
```
