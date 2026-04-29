from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from n8ngd import APP_NAME, __version__
from n8ngd.app_paths import get_logo_path
from n8ngd.logging_service import configure_logging
from n8ngd.mainwindow import MainWindow


def main() -> int:
    app = QApplication([])
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    logo_path = get_logo_path()
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    logger, log_emitter, log_file_path = configure_logging()

    window = MainWindow(logger, log_emitter, log_file_path)
    window.show()
    logger.info("Application startup complete. Version %s", __version__)
    return app.exec()
