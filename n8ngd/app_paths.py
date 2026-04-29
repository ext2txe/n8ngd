from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from n8ngd import APP_NAME


def get_app_data_directory() -> Path:
    app_data_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not app_data_dir:
        return Path.home() / f".{APP_NAME}"

    app_data_path = Path(app_data_dir)
    if app_data_path.name.lower() == APP_NAME.lower() and app_data_path.parent.name.lower() == APP_NAME.lower():
        return app_data_path.parent

    return app_data_path


def get_logo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "logo 180.png"
