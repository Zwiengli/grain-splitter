# Installation

English | [简体中文](INSTALLATION.zh-CN.md)

This guide covers the standard local installation steps for Grain Splitter.

## 1. Clone the repository

```bash
git clone https://github.com/Zwiengli/grain-splitter.git
cd grain-splitter
```

## 2. Create and activate a virtual environment

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Windows Command Prompt

```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Optional runtime dependencies

```bash
python -m pip install -r requirements-optional.txt
```

There are currently no extra runtime image readers to install. Grain Splitter now uses `tifffile` by default for `FFF` / `TIFF` / `TIF`, and falls back to `OpenCV` only when `tifffile` is unavailable. Other formats are opened with `OpenCV`.

## 5. Run the app

```bash
python main.py
```

The compatibility entry point below also works:

```bash
python neg_splitter.py
```
