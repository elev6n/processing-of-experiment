"""Main application window and a consistent light theme."""

from PySide6.QtWidgets import QMainWindow, QScrollArea, QTabWidget

from calc_engine import DirectMeasurementResult, MeasurementValue
from widgets.direct_tab import DirectMeasurementTab
from widgets.indirect_tab import IndirectMeasurementTab
from widgets.least_squares_tab import LeastSquaresTab
from widgets.unequal_tab import UnequalMeasurementTab


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
QComboBox { background-color: #ffffff; color: #24334b; }
QComboBox::drop-down { background-color: #edf3fb; border-left: 1px solid #ccd7e5; width: 22px; }
QComboBox QAbstractItemView { background-color: #ffffff; color: #24334b;
    selection-background-color: #d5e6ff; selection-color: #24334b;
    border: 1px solid #ccd7e5; outline: 0; }
QComboBox QAbstractItemView::item { background-color: #ffffff; color: #24334b; min-height: 24px; }
QComboBox QAbstractItemView::item:selected { background-color: #d5e6ff; color: #24334b; }
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
QScrollArea > QWidget > QWidget { background: #f3f6fa; }
"""


class MainWindow(QMainWindow):
    """Share a session registry between all measurement calculations."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Обработка лабораторного эксперимента")
        self.resize(1280, 900)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(STYLE_SHEET)
        self.tabs = QTabWidget()
        self.direct_tab = DirectMeasurementTab()
        self.indirect_tab = IndirectMeasurementTab()
        self.indirect_scroll = QScrollArea()
        self.indirect_scroll.setWidgetResizable(True)
        self.indirect_scroll.setWidget(self.indirect_tab)
        self.tabs.addTab(self.direct_tab, "Прямые измерения")
        self.tabs.addTab(self.indirect_scroll, "Косвенные измерения")
        self.unequal_tab = UnequalMeasurementTab()
        self.unequal_scroll = QScrollArea()
        self.unequal_scroll.setWidgetResizable(True)
        self.unequal_scroll.setWidget(self.unequal_tab)
        self.tabs.addTab(self.unequal_scroll, "Неравноточные измерения")
        self.least_squares_tab = LeastSquaresTab()
        self.least_squares_scroll = QScrollArea()
        self.least_squares_scroll.setWidgetResizable(True)
        self.least_squares_scroll.setWidget(self.least_squares_tab)
        self.tabs.addTab(self.least_squares_scroll, "Метод наименьших квадратов")
        self.saved_results: dict[str, tuple[str, DirectMeasurementResult | MeasurementValue]] = {}
        self.direct_tab.results_changed.connect(self.save_direct_results)
        self.indirect_tab.result_saved.connect(self.save_result)
        self.unequal_tab.result_saved.connect(self.save_result)
        self.least_squares_tab.result_saved.connect(self.save_result)
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("Прямые расчёты сохраняют точность. Округление источников выбирается на вкладках косвенных и неравноточных измерений.")

    def save_direct_results(self, results: dict) -> None:
        """Publish only newly calculated direct results into the common pool."""
        for name, entry in results.items():
            if entry[1] is self.direct_tab.result:
                self.save_result(name, *entry)

    def save_result(self, name: str, unit: str, result: DirectMeasurementResult | MeasurementValue) -> None:
        """Replace the latest result for a symbol and refresh available sources."""
        self.saved_results[name] = (unit, result)
        self.indirect_tab.update_sources(self.saved_results)
        self.unequal_tab.update_sources(self.saved_results)
        self.least_squares_tab.update_sources(self.saved_results)
