from __future__ import annotations

from PySide6.QtWidgets import QApplication

from n8ngd.mainwindow import MainWindow


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
