"""Launch the desktop experiment processing interface."""

import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main() -> int:
    """Create the application and run the Qt event loop."""
    app = QApplication(sys.argv)
    app.setApplicationName("Обработка эксперимента")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
