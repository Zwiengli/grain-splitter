# ART User Commands

English | [简体中文](ART_USERCOMMANDS.zh-CN.md)

This guide explains how to install the Grain Splitter user commands into ART on Windows.

## Reference Links

- [ART repository](https://github.com/artpixls/ART)
- [ART User Commands documentation](https://artraweditor.github.io/Usercommands)

## What this integration does

After installation, ART can show two Grain Splitter commands in its user command menu:

- `Open in Grain Splitter`
- `Open Folder in Grain Splitter`

These commands pass the current ART selection to Grain Splitter so you can open files or a whole folder directly from ART.

## Before you start

Make sure all of the following are ready:

1. ART is installed on your Windows system.
2. Grain Splitter is already cloned locally.
3. Grain Splitter dependencies are installed in a virtual environment.
4. The project contains:
   `main.py`
   `install_art_usercommands.ps1`

If you have not installed Grain Splitter yet, start with the [Installation Guide](INSTALLATION.md).

## Installation Steps

### 1. Close ART completely

ART may cache user commands while it is running. Close it before installing or updating the Grain Splitter commands.

### 2. Open PowerShell in the project folder

Example:

```powershell
cd D:\neg_splitter_gui
```

### 3. Run the ART installation script

```powershell
powershell -ExecutionPolicy Bypass -File .\install_art_usercommands.ps1
```

## What the installer does

The installer writes user command files to:

```text
%LOCALAPPDATA%\ART\usercommands
```

It installs these files:

- `grain_splitter_files.txt`
- `grain_splitter_files.cmd`
- `grain_splitter_folder.txt`
- `grain_splitter_folder.cmd`

It also auto-detects the project script path and a usable Python interpreter, and then wires ART to launch:

```text
pythonw.exe main.py
```

The ART `.txt` files use the ART user command format described in the official documentation, including:

```text
Command=cmd.exe /c .\grain_splitter_files.cmd
Command=cmd.exe /c .\grain_splitter_folder.cmd
```

## 4. Start ART again

Launch ART after the installer finishes.

## 5. Use the commands inside ART

### Open selected files

1. Select one or more files in ART.
2. Open the ART user commands menu.
3. Run `Open in Grain Splitter`.

### Open a whole folder

1. Select the relevant folder workflow entry in ART.
2. Open the ART user commands menu.
3. Run `Open Folder in Grain Splitter`.

## Troubleshooting

### ART starts Grain Splitter but no files appear

1. Close ART.
2. Run the installer again.
3. Start ART again.

### Paths with spaces or special characters

The current installer is designed to support Windows paths with spaces and common special characters when ART passes them through the user command layer.

### User commands do not appear in ART

Check that these files exist in:

```text
%LOCALAPPDATA%\ART\usercommands
```

If they do not exist, run the installation script again from the Grain Splitter project folder.
