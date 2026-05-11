from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from n8ngd import APP_NAME, __version__
from n8ngd.app_paths import get_logo_path
from n8ngd.logging_service import configure_logging


def main() -> int:
    app = QApplication([])
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    logo_path = get_logo_path()
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    logger, log_emitter, log_file_path = configure_logging()

    try:
        from n8ngd.mainwindow import MainWindow

        window = MainWindow(logger, log_emitter, log_file_path)
    except Exception:
        logger.exception("Application startup failed before the main window was shown.")
        QMessageBox.critical(
            None,
            APP_NAME,
            f"Startup failed. See the log file for details:\n{log_file_path}",
        )
        return 1

    window.show()
    logger.info("Application startup complete. Version %s", __version__)
    return app.exec()
