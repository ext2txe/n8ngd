from __future__ import annotations

from pathlib import Path


def normalize_folder_path(folder_path: str) -> Path:
    path = Path(folder_path).expanduser()
    return path.resolve(strict=False)


def list_files(folder_path: str) -> list[Path]:
    path = normalize_folder_path(folder_path)
    if not path.exists():
        raise FileNotFoundError(f"Folder does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a folder: {path}")

    files = [entry for entry in path.iterdir() if entry.is_file()]
    return sorted(files, key=lambda item: item.name.lower())
