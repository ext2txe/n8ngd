from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

from n8ngd import APP_NAME


class LogEmitter(QObject):
    message_logged = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        self._emitter.message_logged.emit(message)


def get_log_directory() -> Path:
    app_data_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not app_data_dir:
        app_data_dir = str(Path.home() / f".{APP_NAME}")

    app_data_path = Path(app_data_dir)
    if app_data_path.name.lower() != APP_NAME.lower():
        app_data_path = app_data_path / APP_NAME

    log_dir = app_data_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file_path() -> Path:
    date_prefix = datetime.now().strftime("%Y%m%d")
    return get_log_directory() / f"{date_prefix}-{APP_NAME}.log"


def configure_logging() -> tuple[logging.Logger, LogEmitter, Path]:
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    emitter = LogEmitter()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    log_file_path = get_log_file_path()

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    qt_handler = QtLogHandler(emitter)
    qt_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(qt_handler)

    return logger, emitter, log_file_path
