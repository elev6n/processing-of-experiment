"""Main application window and a consistent light theme."""

from PySide6.QtWidgets import QMainWindow, QTabWidget

from widgets.direct_tab import DirectMeasurementTab
from widgets.indirect_tab import IndirectMeasurementTab


STYLE_SHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #24334b; }
QMainWindow, QTabWidget::pane { background: #f3f6fa; }
QTabWidget::pane { border: 1px solid #d5dfec; border-radius: 8px; }
QTabBar::tab { background: #e6edf5; padding: 12px 26px; margin-right: 4px; }
QTabBar::tab:selected { background: #fff; color: #245fbc; }
QGroupBox { background: #fff; border: 1px solid #d5dfec; border-radius: 8px;
    margin-top: 14px; padding: 16px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
QLineEdit, QComboBox, QTextEdit { background: #fff; border: 1px solid #ccd7e5;
    border-radius: 5px; padding: 7px; selection-background-color: #d5e6ff; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #3478d4; }
QLineEdit:read-only { background: #eef3fa; color: #55647a; }
QPushButton { background: #f1f5fa; border: 1px solid #ccd7e5; border-radius: 5px; padding: 9px 12px; }
QPushButton:hover { background: #e2ecfa; }
QPushButton#primary { background: #2866bd; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #1d55a5; }
QPushButton:disabled { background: #e8edf3; color: #8b98aa; }
QTableWidget { background: white; alternate-background-color: #f7faff;
    gridline-color: #b6c9e2; border: 1px solid #c5d4e8; selection-background-color: #dceaff;
    selection-color: #24334b; }
QHeaderView::section { background: #edf3fb; border: 1px solid #c5d4e8;
    padding: 9px 7px; font-weight: 600; }
QLabel#pageTitle { font-size: 20pt; font-weight: 600; padding: 8px 0; }
QLabel#resultCard { background: #edf5ff; color: #174b8d; border: 1px solid #c7ddf9;
    border-radius: 7px; padding: 16px; font-size: 15pt; font-weight: 600; }
QScrollArea { border: none; background: #f3f6fa; }
"""


class MainWindow(QMainWindow):
    """Connect the direct measurement registry to formula input bindings."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Обработка лабораторного эксперимента")
        self.resize(1280, 900)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(STYLE_SHEET)
        self.tabs = QTabWidget()
        self.direct_tab = DirectMeasurementTab()
        self.indirect_tab = IndirectMeasurementTab()
        self.tabs.addTab(self.direct_tab, "Прямые измерения")
        self.tabs.addTab(self.indirect_tab, "Косвенные измерения")
        self.direct_tab.results_changed.connect(self.indirect_tab.update_sources)
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("Расчёты используют исходную точность; округление применяется только к итоговой записи.")
