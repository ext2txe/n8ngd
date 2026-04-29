from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings


class SettingsService:
    def __init__(self) -> None:
        self._settings = QSettings("n8ngd", "n8ngd")

    def get_last_folder_path(self) -> str:
        return self._settings.value("files/last_folder_path", "", type=str)

    def set_last_folder_path(self, path: str) -> None:
        self._settings.setValue("files/last_folder_path", path)

    def get_n8n_webhook_url(self) -> str:
        return self._settings.value("settings/n8n_webhook_url", "", type=str)

    def set_n8n_webhook_url(self, url: str) -> None:
        self._settings.setValue("settings/n8n_webhook_url", url)

    def get_window_geometry(self) -> QByteArray | None:
        geometry = self._settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            return geometry
        return None

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)

    def get_files_splitter_state(self) -> QByteArray | None:
        splitter_state = self._settings.value("files/splitter_state")
        if isinstance(splitter_state, QByteArray):
            return splitter_state
        return None

    def set_files_splitter_state(self, splitter_state: QByteArray) -> None:
        self._settings.setValue("files/splitter_state", splitter_state)

    def get_google_credentials_path(self) -> str:
        return self._settings.value("google_drive/credentials_path", "", type=str)

    def set_google_credentials_path(self, path: str) -> None:
        self._settings.setValue("google_drive/credentials_path", path)

    def get_google_drive_splitter_state(self) -> QByteArray | None:
        splitter_state = self._settings.value("google_drive/splitter_state")
        if isinstance(splitter_state, QByteArray):
            return splitter_state
        return None

    def set_google_drive_splitter_state(self, splitter_state: QByteArray) -> None:
        self._settings.setValue("google_drive/splitter_state", splitter_state)

    def get_google_selected_drive_id(self) -> str:
        return self._settings.value("google_drive/selected_drive_id", "root", type=str)

    def set_google_selected_drive_id(self, drive_id: str) -> None:
        self._settings.setValue("google_drive/selected_drive_id", drive_id)
