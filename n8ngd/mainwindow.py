from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QComboBox,
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
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from n8ngd import APP_NAME, __version__
from n8ngd.app_paths import get_logo_path
from n8ngd.file_service import list_files, normalize_folder_path
from n8ngd.google_drive_service import DriveItem, DriveOption, GoogleDriveService
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


class GoogleDriveConnectWorker(QObject):
    connected = Signal(object)
    failed = Signal(str)

    def __init__(self, drive_service: GoogleDriveService, credentials_path: str) -> None:
        super().__init__()
        self._drive_service = drive_service
        self._credentials_path = credentials_path

    def run(self) -> None:
        try:
            self._drive_service.connect(self._credentials_path)
            drives = self._drive_service.list_drives()
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.connected.emit(drives)


class MainWindow(QMainWindow):
    def __init__(self, logger: logging.Logger, log_emitter: LogEmitter, log_file_path: Path) -> None:
        super().__init__()
        self.logger = logger
        self.log_emitter = log_emitter
        self.log_file_path = log_file_path
        self.settings_service = SettingsService()
        self.google_drive_service = GoogleDriveService()
        self.google_current_drive: DriveOption | None = None
        self.google_folder_stack: list[tuple[str, str]] = []
        self._upload_thread: QThread | None = None
        self._upload_worker: UploadWorker | None = None
        self._google_connect_thread: QThread | None = None
        self._google_connect_worker: GoogleDriveConnectWorker | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(760, 520)
        logo_path = get_logo_path()
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.tabs = QTabWidget()
        self.files_tab = QWidget()
        self.google_drive_tab = QWidget()
        self.settings_tab = QWidget()
        self.log_tab = QWidget()

        self._build_files_tab()
        self._build_google_drive_tab()
        self._build_settings_tab()
        self._build_log_tab()

        self.tabs.addTab(self.files_tab, "Files")
        self.tabs.addTab(self.google_drive_tab, "Google Drive")
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

        file_panel = QWidget()
        file_panel_layout = QVBoxLayout()
        file_panel_layout.setContentsMargins(0, 0, 0, 0)
        file_panel_layout.addWidget(self.file_list)
        file_panel.setLayout(file_panel_layout)

        self.file_preview = QPlainTextEdit()
        self.file_preview.setReadOnly(True)
        self.file_preview.setPlaceholderText("Select a file to preview its contents.")

        preview_panel = QWidget()
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QLabel("Selected file contents"))
        preview_layout.addWidget(self.file_preview)
        preview_panel.setLayout(preview_layout)

        self.files_splitter = QSplitter(Qt.Horizontal)
        self.files_splitter.addWidget(file_panel)
        self.files_splitter.addWidget(preview_panel)
        self.files_splitter.setChildrenCollapsible(False)
        self.files_splitter.setStretchFactor(0, 1)
        self.files_splitter.setStretchFactor(1, 1)

        self.upload_button = QPushButton("Upload Selected File")
        self.upload_button.setEnabled(False)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)

        layout.addLayout(controls_layout)
        layout.addWidget(self.files_splitter, stretch=1)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.status_label)

        self.files_tab.setLayout(layout)

        self.browse_button.clicked.connect(self._choose_folder)
        self.refresh_button.clicked.connect(self.refresh_files)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.upload_button.clicked.connect(self._start_upload)
        self.file_list.itemSelectionChanged.connect(self._update_upload_state)
        self.file_list.itemSelectionChanged.connect(self._update_file_preview)
        self.file_list.currentItemChanged.connect(self._update_file_preview)
        self.file_list.itemClicked.connect(self._update_file_preview)
        self.folder_path_edit.editingFinished.connect(self._save_folder_path)

    def _build_google_drive_tab(self) -> None:
        layout = QVBoxLayout()

        auth_layout = QHBoxLayout()
        self.google_credentials_edit = QLineEdit()
        self.google_credentials_edit.setPlaceholderText("Path to Google OAuth client credentials JSON")
        self.google_credentials_browse_button = QPushButton("Browse...")
        self.google_connect_button = QPushButton("Connect")
        auth_layout.addWidget(QLabel("Credentials"))
        auth_layout.addWidget(self.google_credentials_edit, stretch=1)
        auth_layout.addWidget(self.google_credentials_browse_button)
        auth_layout.addWidget(self.google_connect_button)

        nav_layout = QHBoxLayout()
        self.google_drive_combo = QComboBox()
        self.google_drive_combo.setEnabled(False)
        self.google_up_button = QPushButton("Up")
        self.google_up_button.setEnabled(False)
        self.google_refresh_button = QPushButton("Refresh")
        self.google_refresh_button.setEnabled(False)
        self.google_folder_label = QLabel("Folder: Not connected")
        self.google_folder_label.setTextFormat(Qt.PlainText)
        nav_layout.addWidget(QLabel("Drive"))
        nav_layout.addWidget(self.google_drive_combo, stretch=0)
        nav_layout.addWidget(self.google_up_button)
        nav_layout.addWidget(self.google_refresh_button)
        nav_layout.addWidget(self.google_folder_label, stretch=1)

        self.google_drive_list = QListWidget()
        self.google_drive_list.setSelectionMode(QListWidget.SingleSelection)

        drive_list_panel = QWidget()
        drive_list_layout = QVBoxLayout()
        drive_list_layout.setContentsMargins(0, 0, 0, 0)
        drive_list_layout.addWidget(self.google_drive_list)
        drive_list_panel.setLayout(drive_list_layout)

        self.google_drive_preview = QPlainTextEdit()
        self.google_drive_preview.setReadOnly(True)
        self.google_drive_preview.setPlaceholderText("Select a Google Drive file to preview its contents.")

        drive_preview_panel = QWidget()
        drive_preview_layout = QVBoxLayout()
        drive_preview_layout.setContentsMargins(0, 0, 0, 0)
        drive_preview_layout.addWidget(QLabel("Selected Google Drive item"))
        drive_preview_layout.addWidget(self.google_drive_preview)
        drive_preview_panel.setLayout(drive_preview_layout)

        self.google_drive_splitter = QSplitter(Qt.Horizontal)
        self.google_drive_splitter.addWidget(drive_list_panel)
        self.google_drive_splitter.addWidget(drive_preview_panel)
        self.google_drive_splitter.setChildrenCollapsible(False)
        self.google_drive_splitter.setStretchFactor(0, 1)
        self.google_drive_splitter.setStretchFactor(1, 1)

        self.google_drive_status_label = QLabel("")
        self.google_drive_status_label.setWordWrap(True)
        self.google_drive_status_label.setTextFormat(Qt.PlainText)

        layout.addLayout(auth_layout)
        layout.addLayout(nav_layout)
        layout.addWidget(self.google_drive_splitter, stretch=1)
        layout.addWidget(self.google_drive_status_label)
        self.google_drive_tab.setLayout(layout)

        self.google_credentials_browse_button.clicked.connect(self._choose_google_credentials)
        self.google_connect_button.clicked.connect(self._connect_google_drive)
        self.google_drive_combo.currentIndexChanged.connect(self._google_drive_changed)
        self.google_refresh_button.clicked.connect(self._refresh_google_drive_items)
        self.google_up_button.clicked.connect(self._google_navigate_up)
        self.google_drive_list.itemSelectionChanged.connect(self._update_google_drive_preview)
        self.google_drive_list.currentItemChanged.connect(self._update_google_drive_preview)
        self.google_drive_list.itemDoubleClicked.connect(self._handle_google_drive_item_double_clicked)
        self.google_credentials_edit.editingFinished.connect(self._save_google_credentials_path)

    def _build_settings_tab(self) -> None:
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.n8n_url_edit = QLineEdit()
        self.n8n_url_edit.setPlaceholderText("https://your-n8n-host/webhook/...")
        form_layout.addRow("N8N Webhook URL", self.n8n_url_edit)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        form_layout.addRow("Font Size", self.font_size_spin)

        layout.addLayout(form_layout)
        layout.addStretch(1)
        self.settings_tab.setLayout(layout)

        self.n8n_url_edit.editingFinished.connect(self._save_webhook_url)
        self.font_size_spin.valueChanged.connect(self._save_font_size)

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
        window_geometry = self.settings_service.get_window_geometry()
        if window_geometry:
            self.restoreGeometry(window_geometry)

        splitter_state = self.settings_service.get_files_splitter_state()
        if splitter_state:
            self.files_splitter.restoreState(splitter_state)

        google_splitter_state = self.settings_service.get_google_drive_splitter_state()
        if google_splitter_state:
            self.google_drive_splitter.restoreState(google_splitter_state)

        last_folder = self.settings_service.get_last_folder_path()
        webhook_url = self.settings_service.get_n8n_webhook_url()
        google_credentials_path = self.settings_service.get_google_credentials_path()
        font_size = self.settings_service.get_font_size()
        self.folder_path_edit.setText(last_folder)
        self.n8n_url_edit.setText(webhook_url)
        self.google_credentials_edit.setText(google_credentials_path)
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(font_size)
        self.font_size_spin.blockSignals(False)
        self._apply_font_size(font_size)
        if last_folder:
            self.refresh_files()
        else:
            self.file_preview.setPlainText("")

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

    def _save_google_credentials_path(self) -> None:
        credentials_path = self.google_credentials_edit.text().strip()
        self.settings_service.set_google_credentials_path(credentials_path)
        if credentials_path:
            self.logger.info("Saved Google credentials path: %s", credentials_path)

    def _save_font_size(self, font_size: int) -> None:
        self.settings_service.set_font_size(font_size)
        self._apply_font_size(font_size)
        self.logger.info("Font size set to %s", font_size)

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
        self.file_preview.clear()
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

        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)
            self._update_file_preview()

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
        selected_items = self.file_list.selectedItems()
        item = selected_items[0] if selected_items else self.file_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _update_file_preview(
        self,
        current: QListWidgetItem | None = None,
        previous: QListWidgetItem | None = None,
    ) -> None:
        del previous

        selected_items = self.file_list.selectedItems()
        selected_item = selected_items[0] if selected_items else current or self.file_list.currentItem()
        if selected_item is None:
            self.file_preview.clear()
            return

        file_path = selected_item.data(Qt.UserRole)
        if not file_path:
            self.file_preview.clear()
            return

        path = Path(file_path)
        try:
            preview_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            preview_text = f"Preview unavailable: {exc}"

        self.file_preview.setPlainText(preview_text)
        self.logger.info("Preview updated for %s", path)

    def _choose_google_credentials(self) -> None:
        current = self.google_credentials_edit.text().strip()
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google OAuth Client JSON",
            current or "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected:
            return

        self.google_credentials_edit.setText(selected)
        self._save_google_credentials_path()

    def _connect_google_drive(self) -> None:
        credentials_path = self.google_credentials_edit.text().strip()
        if not credentials_path:
            self._set_google_drive_status("Select a Google OAuth credentials JSON file first.", is_error=True)
            return

        self._save_google_credentials_path()
        self.google_connect_button.setEnabled(False)
        self.google_credentials_browse_button.setEnabled(False)
        self.google_drive_combo.setEnabled(False)
        self.google_refresh_button.setEnabled(False)
        self.google_up_button.setEnabled(False)
        self._set_google_drive_status("Connecting to Google Drive with full Drive access...", is_error=False)
        self.logger.info("Starting Google Drive connection.")

        self._google_connect_thread = QThread(self)
        self._google_connect_worker = GoogleDriveConnectWorker(self.google_drive_service, credentials_path)
        self._google_connect_worker.moveToThread(self._google_connect_thread)
        self._google_connect_thread.started.connect(self._google_connect_worker.run)
        self._google_connect_worker.connected.connect(self._finish_google_drive_connect)
        self._google_connect_worker.failed.connect(self._fail_google_drive_connect)
        self._google_connect_worker.connected.connect(self._google_connect_thread.quit)
        self._google_connect_worker.failed.connect(self._google_connect_thread.quit)
        self._google_connect_worker.connected.connect(self._google_connect_worker.deleteLater)
        self._google_connect_worker.failed.connect(self._google_connect_worker.deleteLater)
        self._google_connect_thread.finished.connect(self._google_connect_thread.deleteLater)
        self._google_connect_thread.finished.connect(self._clear_google_connect_refs)
        self._google_connect_thread.start()

    def _finish_google_drive_connect(self, drives: object) -> None:
        if not isinstance(drives, list):
            self._fail_google_drive_connect("Unexpected Google Drive response.")
            return

        self.google_drive_combo.blockSignals(True)
        self.google_drive_combo.clear()
        for drive in drives:
            if not isinstance(drive, DriveOption):
                continue
            label = drive.name if not drive.is_shared_drive else f"{drive.name} (Shared Drive)"
            self.google_drive_combo.addItem(label, drive)
        self.google_drive_combo.blockSignals(False)

        self.google_drive_combo.setEnabled(True)
        self.google_refresh_button.setEnabled(True)

        desired_drive_id = self.settings_service.get_google_selected_drive_id()
        selected_index = 0
        for index in range(self.google_drive_combo.count()):
            drive = self.google_drive_combo.itemData(index)
            if isinstance(drive, DriveOption) and drive.id == desired_drive_id:
                selected_index = index
                break

        self.google_drive_combo.setCurrentIndex(selected_index)
        self._google_drive_changed(selected_index)
        self.logger.info("Connected to Google Drive.")
        self._set_google_drive_status("Connected to Google Drive with full Drive access.", is_error=False)

    def _fail_google_drive_connect(self, error_message: str) -> None:
        self.logger.error("Google Drive connection failed. %s", error_message)
        self._set_google_drive_status(f"Google Drive connection failed: {error_message}", is_error=True)

    def _clear_google_connect_refs(self) -> None:
        self._google_connect_worker = None
        self._google_connect_thread = None
        self.google_connect_button.setEnabled(True)
        self.google_credentials_browse_button.setEnabled(True)

    def _google_drive_changed(self, index: int) -> None:
        drive = self.google_drive_combo.itemData(index)
        if not isinstance(drive, DriveOption):
            return

        self.google_current_drive = drive
        self.google_folder_stack = [(drive.id, drive.name)]
        self.settings_service.set_google_selected_drive_id(drive.id)
        self._refresh_google_drive_items()

    def _refresh_google_drive_items(self) -> None:
        if self.google_current_drive is None:
            return

        folder_id, _ = self.google_folder_stack[-1]
        self.google_drive_list.clear()
        self.google_drive_preview.clear()

        try:
            items = self.google_drive_service.list_folder_items(self.google_current_drive, folder_id)
        except Exception as exc:
            self.logger.exception("Failed to load Google Drive items.")
            self._set_google_drive_status(f"Failed to load Google Drive items: {exc}", is_error=True)
            return

        for item in items:
            prefix = "[Folder] " if item.is_folder else ""
            list_item = QListWidgetItem(f"{prefix}{item.name}")
            list_item.setData(Qt.UserRole, item)
            self.google_drive_list.addItem(list_item)

        if self.google_drive_list.count() > 0:
            self.google_drive_list.setCurrentRow(0)
            self._update_google_drive_preview()

        path_text = " / ".join(name for _, name in self.google_folder_stack)
        self.google_folder_label.setText(f"Folder: {path_text}")
        self.google_up_button.setEnabled(len(self.google_folder_stack) > 1)
        self._set_google_drive_status(f"Loaded {len(items)} Google Drive item(s).", is_error=False)
        self.logger.info("Loaded %s Google Drive item(s) from %s", len(items), path_text)

    def _google_navigate_up(self) -> None:
        if len(self.google_folder_stack) <= 1:
            return

        self.google_folder_stack.pop()
        self._refresh_google_drive_items()

    def _handle_google_drive_item_double_clicked(self, item: QListWidgetItem) -> None:
        drive_item = item.data(Qt.UserRole)
        if not isinstance(drive_item, DriveItem):
            return

        if not drive_item.is_folder:
            return

        self.google_folder_stack.append((drive_item.id, drive_item.name))
        self._refresh_google_drive_items()

    def _update_google_drive_preview(
        self,
        current: QListWidgetItem | None = None,
        previous: QListWidgetItem | None = None,
    ) -> None:
        del previous

        selected_items = self.google_drive_list.selectedItems()
        selected_item = selected_items[0] if selected_items else current or self.google_drive_list.currentItem()
        if selected_item is None:
            self.google_drive_preview.clear()
            return

        drive_item = selected_item.data(Qt.UserRole)
        if not isinstance(drive_item, DriveItem):
            self.google_drive_preview.clear()
            return

        try:
            preview_text = self.google_drive_service.get_preview_text(drive_item)
        except Exception as exc:
            preview_text = f"Preview unavailable: {exc}"

        self.google_drive_preview.setPlainText(preview_text)
        self.logger.info("Google Drive preview updated for %s", drive_item.name)

    def _set_google_drive_status(self, message: str, *, is_error: bool) -> None:
        color = "#9b1c1c" if is_error else "#1f4d2e"
        self.google_drive_status_label.setStyleSheet(f"color: {color};")
        self.google_drive_status_label.setText(message)

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

    def _apply_font_size(self, font_size: int) -> None:
        app = self.window().windowHandle()
        del app
        qt_app = self.parent()
        del qt_app
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance()
        if application is None:
            return

        font = application.font()
        font.setPointSize(font_size)
        application.setFont(font)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.settings_service.set_window_geometry(self.saveGeometry())
        self.settings_service.set_files_splitter_state(self.files_splitter.saveState())
        self.settings_service.set_google_drive_splitter_state(self.google_drive_splitter.saveState())
        self.logger.info("Application exiting cleanly. Version %s", __version__)
        super().closeEvent(event)
