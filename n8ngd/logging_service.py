from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QtMsgType, Signal, qInstallMessageHandler

from n8ngd import APP_NAME
from n8ngd.app_paths import get_app_data_directory


class LogEmitter(QObject):
    message_logged = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        self._emitter.message_logged.emit(message)


class DotMillisFormatter(logging.Formatter):
    default_msec_format = "%s.%03d"


def _format_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback) -> str:
    logger = logging.getLogger(APP_NAME)
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
    return f"{exc_type.__name__}: {exc_value}"


def install_exception_logging() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        _format_exception(exc_type, exc_value, exc_traceback)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        _format_exception(args.exc_type, args.exc_value, args.exc_traceback)

    qt_levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handle_qt_message(message_type, context, message) -> None:
        logger = logging.getLogger(APP_NAME)
        level = qt_levels.get(message_type, logging.INFO)
        location = ""
        if context.file and context.line:
            location = f" ({Path(context.file).name}:{context.line})"
        logger.log(level, "Qt: %s%s", message, location)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
    qInstallMessageHandler(handle_qt_message)


def get_log_directory() -> Path:
    log_dir = get_app_data_directory() / "log"
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
    formatter = DotMillisFormatter("%(asctime)s [%(levelname)s] %(message)s")
    log_file_path = get_log_file_path()

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    qt_handler = QtLogHandler(emitter)
    qt_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(qt_handler)
    install_exception_logging()

    return logger, emitter, log_file_path
