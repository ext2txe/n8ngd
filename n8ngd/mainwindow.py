from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from n8ngd import __version__
from n8ngd.file_service import list_files, normalize_folder_path
from n8ngd.logging_service import LogEmitter
from n8ngd.settings_service import SettingsService
from n8ngd.upload_service import UploadResult, upload_file, validate_webhook_url


class UploadWorker(QObject):
    finished = Signal(object)

    def __init__(self, file_path: str, webhook_url: str) -> None:
        super().__init__()
        self._file_path = file_path
        self._webhook_url = webhook_url

    def run(self) -> None:
        result = upload_file(self._file_path, self._webhook_url)
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, logger: logging.Logger, log_emitter: LogEmitter, log_file_path: Path) -> None:
        super().__init__()
        self.logger = logger
        self.log_emitter = log_emitter
        self.log_file_path = log_file_path
        self.settings_service = SettingsService()
        self._upload_thread: QThread | None = None
        self._upload_worker: UploadWorker | None = None

        self.setWindowTitle("n8ngd")
        self.resize(760, 520)

        self.tabs = QTabWidget()
        self.files_tab = QWidget()
        self.settings_tab = QWidget()
        self.log_tab = QWidget()

        self._build_files_tab()
        self._build_settings_tab()
        self._build_log_tab()

        self.tabs.addTab(self.files_tab, "Files")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.log_tab, "Log")
        self.setCentralWidget(self.tabs)

        self.log_emitter.message_logged.connect(self._append_log_message)
        self._load_settings()

    def _build_files_tab(self) -> None:
        layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("Path to folder")
        self.browse_button = QPushButton("Browse...")
        self.refresh_button = QPushButton("Refresh")
        self.open_folder_button = QPushButton("Open Folder")

        controls_layout.addWidget(QLabel("Path to folder"))
        controls_layout.addWidget(self.folder_path_edit, stretch=1)
        controls_layout.addWidget(self.browse_button)
        controls_layout.addWidget(self.refresh_button)
        controls_layout.addWidget(self.open_folder_button)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SingleSelection)

        self.upload_button = QPushButton("Upload Selected File")
        self.upload_button.setEnabled(False)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)

        layout.addLayout(controls_layout)
        layout.addWidget(self.file_list, stretch=1)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.status_label)

        self.files_tab.setLayout(layout)

        self.browse_button.clicked.connect(self._choose_folder)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.upload_button.clicked.connect(self._start_upload)
        self.file_list.itemSelectionChanged.connect(self._update_upload_state)
        self.folder_path_edit.editingFinished.connect(self._save_folder_path)

    def _build_settings_tab(self) -> None:
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.n8n_url_edit = QLineEdit()
        self.n8n_url_edit.setPlaceholderText("https://your-n8n-host/webhook/...")
        form_layout.addRow("N8N Webhook URL", self.n8n_url_edit)

        layout.addLayout(form_layout)
        layout.addStretch(1)
        self.settings_tab.setLayout(layout)

        self.n8n_url_edit.editingFinished.connect(self._save_webhook_url)

    def _build_log_tab(self) -> None:
        layout = QVBoxLayout()

        controls_layout = QHBoxLayout()
        self.clear_log_view_button = QPushButton("Clear View")
        self.open_log_file_button = QPushButton("View Log File")
        controls_layout.addWidget(self.clear_log_view_button)
        controls_layout.addWidget(self.open_log_file_button)
        controls_layout.addStretch(1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        layout.addLayout(controls_layout)
        layout.addWidget(self.log_view, stretch=1)
        self.log_tab.setLayout(layout)

        self.clear_log_view_button.clicked.connect(self.log_view.clear)
        self.open_log_file_button.clicked.connect(self._open_log_file)

    def _load_settings(self) -> None:
        last_folder = self.settings_service.get_last_folder_path()
        webhook_url = self.settings_service.get_n8n_webhook_url()
        self.folder_path_edit.setText(last_folder)
        self.n8n_url_edit.setText(webhook_url)
        if last_folder:
            self.refresh_files()

    def _save_folder_path(self) -> None:
        folder_path = self.folder_path_edit.text().strip()
        self.settings_service.set_last_folder_path(folder_path)
        if folder_path:
            self.logger.info("Saved folder path: %s", folder_path)

    def _save_webhook_url(self) -> None:
        webhook_url = self.n8n_url_edit.text().strip()
        self.settings_service.set_n8n_webhook_url(webhook_url)
        if webhook_url:
            self.logger.info("Saved N8N webhook URL.")

    def _choose_folder(self) -> None:
        current = self.folder_path_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select folder", current or "")
        if not selected:
            return
        self.folder_path_edit.setText(selected)
        self._save_folder_path()
        self.logger.info("Selected folder: %s", selected)
        self.refresh_files()

    def refresh_files(self) -> None:
        folder_path = self.folder_path_edit.text().strip()
        self.file_list.clear()
        self.upload_button.setEnabled(False)

        if not folder_path:
            self._set_status("Enter or choose a folder to load files.", is_error=False)
            return

        try:
            files = list_files(folder_path)
        except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            self.logger.error("Failed to load files from %s: %s", folder_path, exc)
            self._set_status(str(exc), is_error=True)
            return

        self._save_folder_path()
        self.logger.info("Loaded %s file(s) from %s", len(files), folder_path)

        for file_path in files:
            item = QListWidgetItem(file_path.name)
            item.setData(Qt.UserRole, str(file_path))
            self.file_list.addItem(item)

        if files:
            self._set_status(f"Loaded {len(files)} file(s).", is_error=False)
        else:
            self._set_status("The selected folder does not contain any files.", is_error=False)

    def _open_folder(self) -> None:
        folder_text = self.folder_path_edit.text().strip()
        if not folder_text:
            self._set_status("Choose a folder before trying to open it.", is_error=True)
            return

        folder_path = normalize_folder_path(folder_text)
        if not folder_path.exists() or not folder_path.is_dir():
            self._set_status(f"Folder is not available: {folder_path}", is_error=True)
            self.logger.error("Open folder failed, path unavailable: %s", folder_path)
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
        self.logger.info("Opened folder: %s", folder_path)

    def _update_upload_state(self) -> None:
        self.upload_button.setEnabled(self.file_list.currentItem() is not None and self._upload_thread is None)

    def _current_selected_file(self) -> str | None:
        item = self.file_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _start_upload(self) -> None:
        file_path = self._current_selected_file()
        if not file_path:
            self._set_status("Select a file before uploading.", is_error=True)
            return

        webhook_url = self.n8n_url_edit.text().strip()
        if not webhook_url:
            self.tabs.setCurrentWidget(self.settings_tab)
            self._set_status("Set the N8N Webhook URL before uploading.", is_error=True)
            return

        try:
            validate_webhook_url(webhook_url)
        except ValueError as exc:
            self.tabs.setCurrentWidget(self.settings_tab)
            self._set_status(str(exc), is_error=True)
            return

        self._save_webhook_url()
        self.upload_button.setEnabled(False)
        self._set_status(f"Uploading {Path(file_path).name}...", is_error=False)
        self.logger.info("Starting upload for %s", file_path)

        self._upload_thread = QThread(self)
        self._upload_worker = UploadWorker(file_path, webhook_url)
        self._upload_worker.moveToThread(self._upload_thread)
        self._upload_thread.started.connect(self._upload_worker.run)
        self._upload_worker.finished.connect(self._finish_upload)
        self._upload_worker.finished.connect(self._upload_thread.quit)
        self._upload_worker.finished.connect(self._upload_worker.deleteLater)
        self._upload_thread.finished.connect(self._upload_thread.deleteLater)
        self._upload_thread.finished.connect(self._clear_upload_refs)
        self._upload_thread.start()

    def _finish_upload(self, result: UploadResult) -> None:
        self._set_status(result.message, is_error=not result.success)
        if result.success:
            self.logger.info("Upload finished successfully. %s", result.message)
        else:
            self.logger.error("Upload failed. %s", result.message)
        if result.success:
            QMessageBox.information(self, "Upload Complete", result.message)

    def _clear_upload_refs(self) -> None:
        self._upload_worker = None
        self._upload_thread = None
        self._update_upload_state()

    def _append_log_message(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _open_log_file(self) -> None:
        if not self.log_file_path.exists():
            self.logger.error("Log file is not available yet: %s", self.log_file_path)
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_file_path)))
        self.logger.info("Opened log file: %s", self.log_file_path)

    def _set_status(self, message: str, *, is_error: bool) -> None:
        color = "#9b1c1c" if is_error else "#1f4d2e"
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(message)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.logger.info("Application exiting cleanly. Version %s", __version__)
        super().closeEvent(event)
