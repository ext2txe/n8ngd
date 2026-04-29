from __future__ import annotations

from PySide6.QtCore import QSettings


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
