"""Linear regression inputs, shared memory sources and Matplotlib plots."""

from pathlib import Path
import re

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from calc_engine import DirectMeasurementResult, InvalidInputError, MeasurementValue, formula_variables
from least_squares import LeastSquaresResult, calculate_least_squares
from widgets.common import CalculationWorker, display, number, result_text
from widgets.error_dialog import ErrorDialog


class AxisInput(QGroupBox):
    """One axis entered manually or assembled from ordered memory snapshots."""

    changed = Signal()

    def __init__(self, axis: str) -> None:
        super().__init__(f"Источник {axis}")
        self.saved_results = {}
        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = QComboBox()
        self.mode.addItems(["Ввести массив вручную", "Выбрать величины из памяти"])
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(10)
        self.values = QTextEdit()
        self.values.setMaximumHeight(70)
        self.values.setPlaceholderText("Числа через пробел, ; или новую строку. Десятичная запятая допустима.")
        self.errors = QLineEdit()
        self.errors.setPlaceholderText("Необязательно: одна общая или N погрешностей")
        self.sources = QListWidget()
        self.sources.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sources.setMaximumHeight(90)
        self.sources.hide()
        self.label = QLineEdit(f"${axis.lower()}$")
        self.unit = QLineEdit()
        form.addRow("Режим", self.mode)
        form.addRow("Значения", self.values)
        form.addRow("Δ точек", self.errors)
        form.addRow("Память", self.sources)
        self.sources.setToolTip("Выберите несколько величин через Ctrl / Shift.")
        form.addRow("Подпись", self.label)
        form.addRow("Единица", self.unit)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        for edit in (self.errors, self.label, self.unit):
            edit.textChanged.connect(lambda _text: self.changed.emit())
        self.values.textChanged.connect(self.changed.emit)
        self.sources.itemSelectionChanged.connect(self.changed.emit)
        self._mode_changed()

    def _mode_changed(self) -> None:
        manual = self.mode.currentIndex() == 0
        self.values.setVisible(manual)
        self.errors.setVisible(manual)
        self.sources.setVisible(not manual)
        form = self.layout()
        form.setRowVisible(self.values, manual)
        form.setRowVisible(self.errors, manual)
        form.setRowVisible(self.sources, not manual)
        self.changed.emit()

    def update_sources(self, results: dict) -> None:
        """Preserve selected symbols while replacing their source snapshots."""
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.sources.selectedItems()]
        changed = any(self.saved_results.get(key) != results.get(key) for key in selected)
        self.saved_results = dict(results)
        self.sources.blockSignals(True)
        self.sources.clear()
        for name, (unit, _) in results.items():
            item = QListWidgetItem(f"{name} ({unit})" if unit else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.sources.addItem(item)
            item.setSelected(name in selected)
        self.sources.blockSignals(False)
        if changed and self.mode.currentIndex() == 1:
            self.changed.emit()

    @staticmethod
    def _parse(text: str) -> list[float]:
        return [number(token, "Массив") for token in re.split(r"[;\s]+", text.strip()) if token]

    def observations(self) -> tuple[list[float], list[float] | None]:
        """Return ordered observations and their unrounded plotting errors."""
        if self.mode.currentIndex() == 0:
            values = self._parse(self.values.toPlainText())
            errors = self._parse(self.errors.text()) or None
            if errors is not None and len(errors) == 1:
                errors *= len(values)
            return values, errors
        values, errors = [], []
        for item in self.sources.selectedItems():
            _, result = self.saved_results[item.data(Qt.ItemDataRole.UserRole)]
            if isinstance(result, DirectMeasurementResult):
                values.extend(result.raw_data)
                errors.extend([result.instr_error] * len(result.raw_data))
            else:
                values.append(result.mean)
                errors.append(result.total_error)
        return values, errors

    def axis_label(self) -> str:
        """Combine the user label and unit without enabling external TeX."""
        return ", ".join(part for part in (self.label.text().strip(), self.unit.text().strip()) if part)


class LeastSquaresTab(QWidget):
    """Fit paired observations and publish coefficients to the session pool."""

    result_saved = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result: LeastSquaresResult | None = None
        self.revision = 0
        self.worker = None
        layout = QVBoxLayout(self)
        title = QLabel("Метод наименьших квадратов")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Классический МНК y = kx + b: минимум 3 пары. ΔX и ΔY используются для крестов погрешностей; "
            "Δk и Δb — стандартные ошибки по остаточной дисперсии. "
            "В памяти прямые серии дают исходные наблюдения и приборную Δ; остальные величины — "
            "одно среднее и его Δ. Несколько источников объединяются в порядке списка; X и Y сопоставляются по позиции."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        axes = QHBoxLayout()
        self.x_input, self.y_input = AxisInput("X"), AxisInput("Y")
        axes.addWidget(self.x_input)
        axes.addWidget(self.y_input)
        layout.addLayout(axes)
        metadata = QHBoxLayout()
        self.k_name, self.b_name = QLineEdit("k"), QLineEdit("b")
        metadata.addWidget(QLabel("Символы в памяти: наклон"))
        metadata.addWidget(self.k_name)
        metadata.addWidget(QLabel("смещение"))
        metadata.addWidget(self.b_name)
        layout.addLayout(metadata)
        buttons = QHBoxLayout()
        self.calculate_button = QPushButton("Рассчитать и построить")
        self.calculate_button.setObjectName("primary")
        self.save_button = QPushButton("Сохранить график (PNG/PDF)")
        self.save_button.setEnabled(False)
        buttons.addWidget(self.calculate_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        self.card = QLabel("Введите данные и нажмите «Рассчитать и построить».")
        self.card.setObjectName("resultCard")
        self.card.setWordWrap(True)
        self.card.setTextFormat(Qt.TextFormat.PlainText)
        self.card.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.card)
        self.figure = Figure(figsize=(7, 4), facecolor="white", layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(320)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.calculate_button.clicked.connect(self.calculate)
        self.save_button.clicked.connect(self.save_plot)
        self.x_input.changed.connect(self.invalidate)
        self.y_input.changed.connect(self.invalidate)
        self.k_name.textChanged.connect(self.invalidate)
        self.b_name.textChanged.connect(self.invalidate)

    def update_sources(self, results: dict) -> None:
        """Refresh both axis selectors from the application memory pool."""
        self.x_input.update_sources(results)
        self.y_input.update_sources(results)

    def invalidate(self) -> None:
        """Discard the displayed fit when inputs change, retaining saved memory."""
        self.revision += 1
        self.result = None
        self.save_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()
        self.card.setText("Данные изменены. Рассчитайте МНК заново.")

    def calculate(self) -> None:
        """Validate a snapshot and calculate the regression off the GUI thread."""
        try:
            names = (self.k_name.text().strip(), self.b_name.text().strip())
            if names[0] == names[1] or any(
                not name.isidentifier() or formula_variables(name) != [name] for name in names
            ):
                raise InvalidInputError("Задайте два разных символа, допустимых в косвенных формулах.")
            x, dx = self.x_input.observations()
            y, dy = self.y_input.observations()
        except ValueError as exc:
            ErrorDialog(exc, {}, self).exec()
            return
        self.invalidate()
        revision = self.revision
        units = (self.x_input.unit.text().strip(), self.y_input.unit.text().strip())
        labels = (self.x_input.axis_label(), self.y_input.axis_label())
        self.calculate_button.setEnabled(False)
        self.worker = CalculationWorker(lambda: calculate_least_squares(x, y, dx, dy))

        def finished(result: LeastSquaresResult) -> None:
            self.calculate_button.setEnabled(True)
            if revision != self.revision:
                return
            try:
                self._plot(result, labels)
            except (ValueError, RuntimeError) as exc:
                self.invalidate()
                ErrorDialog(exc, {"подписи": labels}, self).exec()
                return
            k_unit = f"({units[1] or '1'})/({units[0]})" if units[0] else units[1]
            r = display(result.correlation) if result.correlation is not None else "не определён (Y постоянно)"
            self.card.setText(
                f"y = {display(result.k)}·x + ({display(result.b)})\n"
                f"{result_text(names[0], k_unit, result.k, result.delta_k)}; "
                f"{result_text(names[1], units[1], result.b, result.delta_b)}\n"
                f"r Пирсона = {r}; остаточная дисперсия = {display(result.residual_variance)}"
            )
            self.result_saved.emit(names[0], k_unit, MeasurementValue(result.k, result.delta_k))
            self.result_saved.emit(names[1], units[1], MeasurementValue(result.b, result.delta_b))
            # Publishing may invalidate this fit if it replaces a selected input.
            if revision == self.revision:
                self.result = result
                self.save_button.setEnabled(True)

        def failed(error: Exception, stack: str) -> None:
            self.calculate_button.setEnabled(True)
            if revision == self.revision:
                ErrorDialog(error, {"X": x, "Y": y, "ΔX": dx, "ΔY": dy}, self, stack).exec()

        self.worker.signals.succeeded.connect(finished)
        self.worker.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(self.worker)

    def _plot(self, result: LeastSquaresResult, labels: tuple[str, str]) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot()
        ax.errorbar(result.x, result.y, xerr=result.delta_x, yerr=result.delta_y,
                    fmt="o", color="#245fbc", ecolor="#7a98bd", capsize=4, label="Эксперимент")
        line_x = np.linspace(min(result.x), max(result.x), 200)
        # Center the prediction to reduce cancellation with large offsets.
        line_y = result.k * (line_x - result.x[0]) + (result.k * result.x[0] + result.b)
        ax.plot(line_x, line_y, color="#db7040", label=rf"МНК: $y = {result.k:.5g}x + ({result.b:.5g})$")
        ax.set_xlabel(labels[0], fontfamily="DejaVu Sans", usetex=False)
        ax.set_ylabel(labels[1], fontfamily="DejaVu Sans", usetex=False)
        ax.set_facecolor("#f7faff")
        ax.grid(True, alpha=0.3)
        ax.legend()
        self.canvas.draw()
        self.toolbar.update()

    def save_plot(self) -> None:
        """Export the current plot with a format chosen in the native dialog."""
        if self.result is None:
            return
        filename, selected = QFileDialog.getSaveFileName(self, "Сохранить график", "mnk.png", "PNG (*.png);;PDF (*.pdf)")
        if not filename:
            return
        suffix = ".pdf" if selected.startswith("PDF") else ".png"
        path = Path(filename)
        if path.suffix.lower() not in (".png", ".pdf"):
            path = path.with_suffix(suffix)
        try:
            self.figure.savefig(path, dpi=200, bbox_inches="tight")
        except (OSError, ValueError, RuntimeError) as exc:
            ErrorDialog(exc, {"файл": str(path)}, self).exec()
