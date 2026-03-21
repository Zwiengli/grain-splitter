from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


FILES_COMMAND_NAME = "grain_splitter_files"
FOLDER_COMMAND_NAME = "grain_splitter_folder"


@dataclass(frozen=True)
class LaunchTarget:
    mode: str
    command_path: Path
    script_path: Path | None = None


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_art_usercommands_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise RuntimeError("LOCALAPPDATA is not set, so the ART usercommands folder could not be located.")
    return Path(local_appdata) / "ART" / "usercommands"


def detect_launch_target(project_root: Path, *, prefer_python: bool = True) -> LaunchTarget:
    project_root = project_root.resolve()
    script_path = project_root / "main.py"
    python_target: LaunchTarget | None = None
    if script_path.exists():
        python_candidates = [
            project_root / "venv" / "Scripts" / "pythonw.exe",
            project_root / "venv" / "Scripts" / "python.exe",
            Path(sys.executable).resolve(),
        ]
        for candidate in python_candidates:
            if candidate.exists():
                python_target = LaunchTarget(
                    mode="python",
                    command_path=candidate.resolve(),
                    script_path=script_path.resolve(),
                )
                break

    if python_target is not None:
        return python_target

    raise RuntimeError("Could not find a usable Python interpreter for main.py.")


def write_text_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(content)


def build_launcher_script(target: LaunchTarget, *, pass_mode: str) -> str:
    if pass_mode == "folder":
        setup_lines = [
            "setlocal DisableDelayedExpansion",
            "set \"GS_FOLDER=%*\"",
            "if not defined GS_FOLDER exit /b 0",
            "set \"GS_FOLDER=%GS_FOLDER:\"=%\"",
        ]
        arg_text = '--folder-raw "%GS_FOLDER%"'
    elif pass_mode == "files":
        setup_lines = [
            "setlocal DisableDelayedExpansion",
        ]
        arg_text = "--files %*"
    else:
        raise RuntimeError(f"Unknown pass mode: {pass_mode}")

    if target.mode == "exe":
        launch_line = f'"{target.command_path}" {arg_text}'
    else:
        if target.script_path is None:
            raise RuntimeError("Python launch target requires a script path.")
        launch_line = f'"{target.command_path}" "{target.script_path}" {arg_text}'

    return "\r\n".join(
        ["@echo off", *setup_lines, launch_line, "exit /b 0", ""]
    )


def build_usercommand_text(
    label: str,
    launcher_file_name: str,
    *,
    file_type: str | None = None,
    min_args: int | None = 1,
    max_args: int | None = None,
) -> str:
    lines = [
        "[ART UserCommand]",
        "",
        f"Label={label}",
        f"Command=cmd.exe /c .\\\\{launcher_file_name}",
    ]
    if file_type:
        lines.append(f"FileType={file_type}")
    if min_args is not None:
        lines.append(f"MinArgs={min_args}")
    if max_args is not None:
        lines.append(f"MaxArgs={max_args}")
    lines.append("")
    return "\r\n".join(lines)


def install_art_usercommands(
    *,
    project_root: str | Path | None = None,
    usercommands_dir: str | Path | None = None,
    target_exe: str | Path | None = None,
    target_python: str | Path | None = None,
    target_script: str | Path | None = None,
    prefer_python: bool = True,
) -> dict:
    project_root_path = Path(project_root) if project_root is not None else get_project_root()
    usercommands_path = Path(usercommands_dir) if usercommands_dir is not None else get_art_usercommands_dir()

    if target_exe is not None:
        launch_target = LaunchTarget(mode="exe", command_path=Path(target_exe).resolve())
    elif target_python is not None or target_script is not None:
        if target_python is None or target_script is None:
            raise RuntimeError("Both target_python and target_script must be provided together.")
        launch_target = LaunchTarget(
            mode="python",
            command_path=Path(target_python).resolve(),
            script_path=Path(target_script).resolve(),
        )
    else:
        launch_target = detect_launch_target(project_root_path, prefer_python=prefer_python)

    if not launch_target.command_path.exists():
        raise RuntimeError(f"Launch target does not exist: {launch_target.command_path}")
    if launch_target.script_path is not None and not launch_target.script_path.exists():
        raise RuntimeError(f"Startup script does not exist: {launch_target.script_path}")

    usercommands_path.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    launcher_specs = {
        FILES_COMMAND_NAME: build_launcher_script(launch_target, pass_mode="files"),
        FOLDER_COMMAND_NAME: build_launcher_script(launch_target, pass_mode="folder"),
    }
    for stem, launcher_content in launcher_specs.items():
        launcher_path = usercommands_path / f"{stem}.cmd"
        write_text_file(launcher_path, launcher_content)
        written_paths.append(launcher_path)

    descriptors = {
        f"{FILES_COMMAND_NAME}.txt": build_usercommand_text(
            "Open in Grain Splitter",
            f"{FILES_COMMAND_NAME}.cmd",
            min_args=1,
        ),
        f"{FOLDER_COMMAND_NAME}.txt": build_usercommand_text(
            "Open Folder in Grain Splitter",
            f"{FOLDER_COMMAND_NAME}.cmd",
            file_type="directory",
            min_args=1,
            max_args=1,
        ),
    }
    for file_name, content in descriptors.items():
        descriptor_path = usercommands_path / file_name
        write_text_file(descriptor_path, content)
        written_paths.append(descriptor_path)

    return {
        "project_root": str(project_root_path.resolve()),
        "usercommands_dir": str(usercommands_path.resolve()),
        "target_mode": launch_target.mode,
        "target_command": str(launch_target.command_path),
        "target_script": str(launch_target.script_path) if launch_target.script_path else "",
        "written_files": [str(path) for path in written_paths],
    }


def build_summary(result: dict) -> str:
    lines = [
        "ART user commands installed.",
        f"Usercommands directory: {result['usercommands_dir']}",
        f"Launch mode: {result['target_mode']}",
        f"Launch command: {result['target_command']}",
    ]
    if result.get("target_script"):
        lines.append(f"Launch script: {result['target_script']}")
    lines.append("Written files:")
    lines.extend(f"  - {path}" for path in result["written_files"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install ART usercommands for Grain Splitter.",
    )
    parser.add_argument("--project-root", default=None, help="Project root directory.")
    parser.add_argument("--usercommands-dir", default=None, help="ART usercommands directory override.")
    parser.add_argument("--target-exe", default=None, help="Use this Grain Splitter executable.")
    parser.add_argument("--target-python", default=None, help="Use this Python interpreter.")
    parser.add_argument("--target-script", default=None, help="Use this script with --target-python.")
    args = parser.parse_args(argv)

    result = install_art_usercommands(
        project_root=args.project_root,
        usercommands_dir=args.usercommands_dir,
        target_exe=args.target_exe,
        target_python=args.target_python,
        target_script=args.target_script,
        prefer_python=True,
    )
    print(build_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
