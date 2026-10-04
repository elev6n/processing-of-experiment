"""Direct measurement input and a laboratory notebook style result table."""

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from calc_engine import DirectMeasurementResult, InvalidInputError, calculate_direct_measurement
from widgets.common import CalculationWorker, display, number, numeric_edit, result_text
from widgets.error_dialog import ErrorDialog


class MeasurementTable(QTableWidget):
    """Editable measurement column with atomic spreadsheet clipboard insertion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["№", "Значение xᵢ"])
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 55)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

    def renumber(self) -> None:
        """Refresh immutable observation numbers after structural changes."""
        for row in range(self.rowCount()):
            item = QTableWidgetItem(str(row + 1))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, item)

    def paste(self) -> None:
        """Validate the entire clipboard before replacing rows at the selection."""
        text = QApplication.clipboard().text()
        try:
            lines = text.strip().splitlines()
            if not lines:
                raise InvalidInputError("Буфер обмена пуст. Скопируйте столбец чисел.")
            if len(lines) > 10000:
                raise InvalidInputError("За один раз можно вставить не более 10 000 измерений.")
            values = []
            for index, line in enumerate(lines):
                cells = line.strip().split("\t")
                if len(cells) != 1:
                    raise InvalidInputError("Скопируйте один столбец значений без заголовка и номеров строк.")
                values.append(number(cells[0], f"Строка {index + 1}"))
            start = max(0, self.currentRow())
            self.setRowCount(max(self.rowCount(), start + len(values)))
            for row, value in enumerate(values, start):
                self.setItem(row, 1, QTableWidgetItem(str(value).replace(".", ",")))
            self.renumber()
            self.setCurrentCell(start, 1)
        except Exception as exc:
            ErrorDialog(exc, {"clipboard": text}, self).exec()

    def keyPressEvent(self, event) -> None:
        """Handle Ctrl+V when the measurement table has focus."""
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
            event.accept()
        else:
            super().keyPressEvent(event)


class DirectMeasurementTab(QWidget):
    """Calculate and retain named direct measurements for indirect formulas."""

    results_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.saved_results: dict[str, tuple[str, DirectMeasurementResult]] = {}
        self.result: DirectMeasurementResult | None = None
        self.revision = 0
        self.worker = None
        layout = QVBoxLayout(self)
        title = QLabel("Прямые измерения")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Введите серию измерений. Все значения и погрешности — в одной единице."))
        settings = QGroupBox("Параметры величины")
        form = QHBoxLayout(settings)
        self.name = QLineEdit("d")
        self.unit = QLineEdit("мм")
        self.theta = numeric_edit("0,00653", nonnegative=True)
        self.alpha = QComboBox()
        self.alpha.addItems(["0.90", "0.95", "0.99"])
        self.alpha.setCurrentText("0.95")
        for label, field in [("Символ", self.name), ("Единица", self.unit), ("Приборная погрешность θ", self.theta), ("Вероятность α", self.alpha)]:
            column = QFormLayout()
            column.addRow(label, field)
            form.addLayout(column)
        layout.addWidget(settings)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        input_box = QGroupBox("Измерения")
        input_layout = QVBoxLayout(input_box)
        self.table = MeasurementTable()
        self.table.setRowCount(5)
        self.table.renumber()
        input_layout.addWidget(self.table)
        paste_hint = QLabel("Ctrl+V — вставить столбец из Excel или Google Таблиц")
        paste_hint.setWordWrap(True)
        input_layout.addWidget(paste_hint)
        for labels in [[("Добавить строку", self.add_row), ("Удалить строку", self.remove_rows)], [("Вставить", self.table.paste), ("Очистить таблицу", self.clear)]]:
            buttons = QHBoxLayout()
            for label, handler in labels:
                button = QPushButton(label)
                button.clicked.connect(handler)
                buttons.addWidget(button)
            input_layout.addLayout(buttons)
        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.setObjectName("primary")
        self.calculate_button.clicked.connect(self.calculate)
        input_layout.addWidget(self.calculate_button)
        splitter.addWidget(input_box)
        output = QGroupBox("Таблица обработки измерений")
        output_layout = QVBoxLayout(output)
        self.output_table = QTableWidget(0, 8)
        self.output_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.output_table.verticalHeader().hide()
        self.output_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.output_table.horizontalHeader().setStretchLastSection(True)
        for column in range(4, 8):
            self.output_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.output_table.setColumnWidth(column, 115)
        output_layout.addWidget(self.output_table)
        self.summary = QLabel("Среднее и сумма квадратов отклонений появятся после расчёта.")
        self.summary.setWordWrap(True)
        output_layout.addWidget(self.summary)
        self.card = QLabel("Добавьте измерения и нажмите «Рассчитать».")
        self.card.setObjectName("resultCard")
        self.card.setWordWrap(True)
        self.card.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_layout.addWidget(self.card)
        self.statistics = QLabel()
        self.statistics.setWordWrap(True)
        output_layout.addWidget(self.statistics)
        copy_layout = QHBoxLayout()
        self.copy_text = QPushButton("Скопировать текст")
        self.copy_latex = QPushButton("Скопировать LaTeX")
        self.copy_text.clicked.connect(lambda: self.copy_result(False))
        self.copy_latex.clicked.connect(lambda: self.copy_result(True))
        for button in [self.copy_text, self.copy_latex]:
            button.setEnabled(False)
            copy_layout.addWidget(button)
        output_layout.addLayout(copy_layout)
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([300, 900])
        layout.addWidget(splitter, 1)
        self.saved_label = QLabel("Сохранённые величины: пока нет. Результат сохраняется после каждого расчёта.")
        self.saved_label.setWordWrap(True)
        layout.addWidget(self.saved_label)
        self.table.itemChanged.connect(self.invalidate)
        for edit in [self.name, self.unit, self.theta]:
            edit.textChanged.connect(self.invalidate)
        self.alpha.currentTextChanged.connect(self.invalidate)

    def invalidate(self, *_args) -> None:
        """Prevent old output from being copied after input edits."""
        self.revision += 1
        self.result = None
        self.copy_text.setEnabled(False)
        self.copy_latex.setEnabled(False)
        self.output_table.clearSpans()
        self.output_table.setRowCount(0)
        self.card.setText("Данные изменены. Нажмите «Рассчитать».")
        self.summary.clear()
        self.statistics.clear()

    def add_row(self) -> None:
        """Append one editable observation."""
        self.table.insertRow(self.table.rowCount())
        self.table.renumber()
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)
        self.invalidate()

    def remove_rows(self) -> None:
        """Remove selected rows, or the last row when there is no selection."""
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows and self.table.rowCount():
            rows.add(self.table.rowCount() - 1)
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
        self.table.renumber()
        self.invalidate()

    def clear(self) -> None:
        """Clear the working series while retaining previously calculated quantities."""
        self.table.setRowCount(0)
        self.invalidate()

    def inputs(self) -> dict:
        """Capture raw user data for calculation diagnostics."""
        return {"name": self.name.text(), "unit": self.unit.text(), "theta": self.theta.text(), "alpha": self.alpha.currentText(), "measurements": [self.table.item(row, 1).text() if self.table.item(row, 1) else "" for row in range(self.table.rowCount())]}

    def calculate(self) -> None:
        """Validate inputs and start a background engine calculation."""
        inputs = self.inputs()
        try:
            name = self.name.text().strip()
            if not name:
                raise InvalidInputError("Укажите символ измеряемой величины.")
            values = [number(text, f"Измерение {i + 1}") for i, text in enumerate(inputs["measurements"])]
            if not values:
                raise InvalidInputError("Добавьте хотя бы одно измерение.")
            theta = number(self.theta.text(), "Приборная погрешность", True)
            alpha = float(self.alpha.currentText())
            self.pending = (self.revision, name, self.unit.text().strip(), inputs)
            self.calculate_button.setEnabled(False)
            self.calculate_button.setText("Вычисление…")
            self.worker = CalculationWorker(lambda: calculate_direct_measurement(values, theta, alpha))
            self.worker.signals.succeeded.connect(self.show_result)
            self.worker.signals.failed.connect(self.calculation_failed)
            QThreadPool.globalInstance().start(self.worker)
        except Exception as exc:
            ErrorDialog(exc, inputs, self).exec()

    def finish(self) -> None:
        """Restore the calculation button after a worker completes."""
        self.calculate_button.setEnabled(True)
        self.calculate_button.setText("Рассчитать")

    def calculation_failed(self, error: Exception, stack: str) -> None:
        """Display engine failure diagnostics captured in the background thread."""
        self.finish()
        ErrorDialog(error, self.pending[3], self, stack).exec()

    def show_result(self, result: DirectMeasurementResult) -> None:
        """Render observation rows and vertically merged uncertainty columns."""
        self.finish()
        revision, name, unit, _ = self.pending
        if revision != self.revision:
            return
        self.result = result
        self.saved_results[name] = (unit, result)
        suffix = f", {unit}" if unit else ""
        self.output_table.clearSpans()
        self.output_table.setRowCount(result.n)
        self.output_table.setHorizontalHeaderLabels(["№", f"{name}ᵢ{suffix}", f"{name}ᵢ − {name}̄{suffix}", f"({name}ᵢ − {name}̄)²" + (f", {unit}²" if unit else ""), f"Sₓ̄{suffix}", f"Δ{name}сл{suffix}", f"Δ{name}пр{suffix}", f"Δ{name}{suffix}"])
        for row, values in enumerate(result.table_rows):
            for column, key in enumerate(["i", "x", "diff", "diff_sq"]):
                self.set_output(row, column, str(row + 1) if column == 0 else display(values[key]))
        for column, value in enumerate([result.std_error, result.random_error, result.instr_error, result.total_error], 4):
            self.set_output(0, column, display(value))
            if result.n > 1:
                self.output_table.setSpan(0, column, result.n, 1)
        self.summary.setText(f"{name}̄ = {display(result.mean)} {unit}     Σ({name}ᵢ − {name}̄)² = {display(sum(row['diff_sq'] for row in result.table_rows))} {unit}²")
        self.card.setText(result_text(name, unit, result.mean, result.total_error) + f"\nε = {display(result.relative_error_pct)} %" if result.mean else result_text(name, unit, result.mean, result.total_error) + "\nε не определена при нулевом среднем")
        self.statistics.setText(f"N = {result.n}  ·  Sₓ = Sₓ̄ = {display(result.std_error)} {unit}  ·  tα,N = {display(result.t_student)}\nSₓ в движке обозначает стандартную ошибку среднего; α = {self.alpha.currentText()}.")
        self.copy_text.setEnabled(True)
        self.copy_latex.setEnabled(True)
        self.saved_label.setText("Сохранённые величины: " + ", ".join(self.saved_results) + ". Доступны для привязки на вкладке косвенных измерений.")
        self.results_changed.emit(dict(self.saved_results))

    def set_output(self, row: int, column: int, text: str) -> None:
        """Insert a centered result table cell."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.output_table.setItem(row, column, item)

    def copy_result(self, latex: bool) -> None:
        """Copy the current rounded result using the selected representation."""
        if self.result:
            QApplication.clipboard().setText(result_text(self.name.text().strip(), self.unit.text().strip(), self.result.mean, self.result.total_error, latex))
