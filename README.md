# Grain Splitter

English | [简体中文](README.zh-CN.md)

[License](LICENSE) | [许可证说明](LICENSE.zh-CN.md)

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

### Input formats

- `FFF`
- `TIFF` / `TIF`
- `JPG` / `JPEG`
- `PNG`
- `BMP`
- `WEBP`

### Output formats

- Original format when possible
- `JPG`
- `PNG`
- `TIFF`

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-name>/grain-splitter.git
cd grain-splitter
```

### 2. Create and activate a virtual environment

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Windows Command Prompt

```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Optional dependency for additional `FFF` / RAW compatibility

```bash
python -m pip install -r requirements-optional.txt
```

`rawpy` is optional. The app already tries `tifffile`, `Pillow`, and `OpenCV`, but `rawpy` can help with some RAW-like `FFF` files.

### 5. Run the app

```bash
python main.py
```

The compatibility entry point below also works:

```bash
python neg_splitter.py
```

## Requirements

- Python 3.10 or newer is recommended.
- `tkinter` is included in most Windows and macOS Python installers.
- On Linux, you may need to install the system Tk package separately before running the app.

## Repository Layout

```text
.
├─ app/          # GUI, preview canvas, settings, theme glue
├─ core/         # Image loading, detection, export, shared constants
├─ i18n/         # UI language files
├─ config/       # Default settings and local user settings
├─ main.py       # Main entry point
└─ neg_splitter.py
```

## GitHub-Friendly Project Files

- [`requirements.txt`](requirements.txt): core runtime dependencies.
- [`requirements-optional.txt`](requirements-optional.txt): optional extra dependency for wider `FFF` support.
- [`.gitignore`](.gitignore): ignores virtual environments, caches, local settings, exports, and large local sample files.
- [`README.zh-CN.md`](README.zh-CN.md): Chinese documentation entry for GitHub readers.
- [`LICENSE`](LICENSE): English license text.
- [`LICENSE.zh-CN.md`](LICENSE.zh-CN.md): Chinese license note and reading guide.

## Notes

- The project stores user-specific settings in `config/user_settings.json`. This file is ignored by Git.
- Large local sample scans such as `001.fff` are ignored by default so the repository stays lightweight.
- If you plan to publish the repository publicly, consider adding a `LICENSE` file that matches how you want others to use the project.
