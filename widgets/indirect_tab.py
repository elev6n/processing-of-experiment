"""Formula editing and propagation from manually entered or linked inputs."""

from PySide6.QtCore import QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from calc_engine import (
    DirectMeasurementResult, IndirectMeasurementResult, InvalidInputError, MeasurementValue,
    calculate_indirect_measurement, formula_variables, round_measurement,
)
from widgets.common import CalculationWorker, display, number, numeric_edit, result_text
from widgets.error_dialog import ErrorDialog


class VariableRow(QGroupBox):
    """A single formula input with optional binding to a saved result."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self.mean = numeric_edit()
        self.error = numeric_edit(nonnegative=True)
        self.source = QComboBox()
        self.source.addItem("Ввести вручную", None)
        self.unit = QLabel()
        form = QHBoxLayout(self)
        for label, widget in [("Источник", self.source), ("Среднее x̄", self.mean), ("Погрешность Δx", self.error)]:
            column = QFormLayout()
            column.addRow(label, widget)
            form.addLayout(column)
        form.addWidget(self.unit)


class IndirectMeasurementTab(QWidget):
    """Discover formula variables and calculate independent error propagation."""

    result_saved = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: dict[str, VariableRow] = {}
        self.saved_results: dict[str, tuple[str, DirectMeasurementResult | MeasurementValue]] = {}
        self.result: IndirectMeasurementResult | None = None
        self.revision = 0
        self.parse_revision = 0
        self.parse_worker = None
        self.parse_busy = False
        self.parsed_formula: str | None = None
        self.parse_error: Exception | None = None
        self.worker = None
        layout = QVBoxLayout(self)
        title = QLabel("Косвенные измерения")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Задайте формулу и укажите значения независимых переменных."))
        settings = QGroupBox("Формула и результат")
        form = QFormLayout(settings)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText("Например: m * v^2 / 2")
        self.formula.setMaxLength(1000)
        self.name = QLineEdit("F")
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("Например: Дж")
        form.addRow("F =", self.formula)
        form.addRow("Символ результата", self.name)
        form.addRow("Единица результата", self.unit)
        layout.addWidget(settings)
        hint = QLabel("Степень: ^ или **. Функции: sqrt, sin, cos, tan, asin, acos, atan, exp, log, ln, lg, abs. Константы: pi, E.\nПогрешности независимы. При работе с разными единицами приведите значения к согласованной системе.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.round_sources = QCheckBox("Использовать округлённые значения сохранённых величин")
        self.round_sources.setChecked(True)
        self.round_sources.setToolTip("Среднее и погрешность округляются как в итоговой карточке. Ручной ввод используется без изменений.")
        self.round_sources.toggled.connect(self.refresh_sources)
        layout.addWidget(self.round_sources)
        self.parse_status = QLabel("Введите формулу — поля переменных появятся автоматически.")
        self.parse_status.setWordWrap(True)
        layout.addWidget(self.parse_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(140)
        self.variable_container = QWidget()
        self.variable_layout = QVBoxLayout(self.variable_container)
        self.variable_layout.addStretch()
        scroll.setWidget(self.variable_container)
        layout.addWidget(scroll, 1)
        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.setObjectName("primary")
        self.calculate_button.setEnabled(False)
        self.calculate_button.clicked.connect(self.calculate)
        layout.addWidget(self.calculate_button)
        results = QGroupBox("Результат и аналитическая погрешность")
        output = QVBoxLayout(results)
        self.card = QLabel("Результат появится после расчёта.")
        self.card.setObjectName("resultCard")
        self.card.setWordWrap(True)
        self.card.setMinimumHeight(90)
        output.addWidget(self.card)
        output.addWidget(QLabel("Формулы LaTeX (можно выделить и скопировать):"))
        self.formula_output = QTextEdit()
        self.formula_output.setReadOnly(True)
        self.formula_output.setMinimumHeight(80)
        self.formula_output.setMaximumHeight(90)
        output.addWidget(self.formula_output)
        self.steps_toggle = QPushButton("Показать ход расчёта / формулы подстановки")
        self.steps_toggle.setCheckable(True)
        self.steps_toggle.setEnabled(False)
        self.steps_toggle.toggled.connect(self.toggle_steps)
        output.addWidget(self.steps_toggle)
        self.steps_output = QTextEdit()
        self.steps_output.setReadOnly(True)
        self.steps_output.setMinimumHeight(100)
        self.steps_output.setMaximumHeight(180)
        self.steps_output.hide()
        output.addWidget(self.steps_output)
        copy_row = QHBoxLayout()
        self.copy_text = QPushButton("Скопировать текст")
        self.copy_latex = QPushButton("Скопировать LaTeX")
        self.copy_text.clicked.connect(lambda: self.copy_result(False))
        self.copy_latex.clicked.connect(lambda: self.copy_result(True))
        for button in [self.copy_text, self.copy_latex]:
            button.setEnabled(False)
            copy_row.addWidget(button)
        output.addLayout(copy_row)
        layout.addWidget(results)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.parse_formula)
        self.formula.textChanged.connect(self.formula_changed)
        self.name.textChanged.connect(self.invalidate)
        self.unit.textChanged.connect(self.invalidate)

    def normalized_formula(self) -> str:
        """Convert the conventional power notation into engine syntax."""
        return self.formula.text().strip().replace("^", "**")

    def invalidate(self, *_args) -> None:
        """Clear output after formula, source or numeric inputs change."""
        self.revision += 1
        self.result = None
        self.card.setText("Данные изменены. Нажмите «Рассчитать».")
        self.formula_output.clear()
        self.steps_output.clear()
        self.steps_toggle.setChecked(False)
        self.steps_toggle.setEnabled(False)
        self.copy_text.setEnabled(False)
        self.copy_latex.setEnabled(False)

    def formula_changed(self) -> None:
        """Debounce parsing and disable calculation until current syntax is valid."""
        self.invalidate()
        self.parse_revision += 1
        self.parsed_formula = None
        self.parse_error = None
        self.calculate_button.setEnabled(False)
        self.parse_status.setText("Проверка формулы…")
        self.timer.start()

    def parse_formula(self) -> None:
        """Use the validated SymPy engine parser in a background thread."""
        if self.parse_busy:
            return
        self.parse_busy = True
        self.pending_parse_revision = self.parse_revision
        formula = self.normalized_formula()
        self.parse_worker = CalculationWorker(lambda: formula_variables(formula))
        self.parse_worker.signals.succeeded.connect(self.parsed)
        self.parse_worker.signals.failed.connect(self.parse_failed)
        QThreadPool.globalInstance().start(self.parse_worker)

    def parse_is_current(self) -> bool:
        """Discard old parses and schedule the latest text when necessary."""
        self.parse_busy = False
        if self.pending_parse_revision != self.parse_revision:
            self.timer.start()
            return False
        return True

    def parsed(self, names: list[str]) -> None:
        """Reconcile variable fields while retaining input for unchanged names."""
        if not self.parse_is_current():
            return
        for name in list(self.rows):
            if name not in names:
                row = self.rows.pop(name)
                self.variable_layout.removeWidget(row)
                row.deleteLater()
        for name in names:
            if name not in self.rows:
                row = VariableRow(name)
                self.rows[name] = row
                self.variable_layout.insertWidget(self.variable_layout.count() - 1, row)
                row.mean.textChanged.connect(self.invalidate)
                row.error.textChanged.connect(self.invalidate)
                row.source.currentIndexChanged.connect(lambda _index, key=name: self.apply_source(key))
                self.populate_source(row)
        self.parsed_formula = self.normalized_formula()
        self.parse_status.setText("Переменные: " + ", ".join(names) if names else "Формула без переменных: погрешность равна нулю.")
        self.calculate_button.setEnabled(self.worker is None)

    def parse_failed(self, error: Exception, stack: str) -> None:
        """Show non-modal validation feedback while the user is typing."""
        if self.parse_is_current():
            self.parse_error = error
            self.parse_status.setText(f"Ошибка в формуле: {error}")
            self.calculate_button.setEnabled(True if self.worker is None else False)

    def populate_source(self, row: VariableRow) -> None:
        """Refresh saved results preserving the selected source."""
        selected = row.source.currentData()
        row.source.blockSignals(True)
        row.source.clear()
        row.source.addItem("Ввести вручную", None)
        for name, (unit, _result) in self.saved_results.items():
            row.source.addItem(f"{name} ({unit})" if unit else name, name)
        index = row.source.findData(selected)
        row.source.setCurrentIndex(max(0, index))
        row.source.blockSignals(False)

    def update_sources(self, results: dict) -> None:
        """Refresh changed bindings, keeping unrelated current output intact."""
        previous = self.saved_results
        self.saved_results = dict(results)
        for name, row in self.rows.items():
            selected = row.source.currentData()
            self.populate_source(row)
            if selected is not None and previous.get(selected) != results.get(selected):
                self.apply_source(name)

    def refresh_sources(self) -> None:
        """Apply the selected precision mode to all linked fields."""
        for name, row in self.rows.items():
            if row.source.currentData() in self.saved_results:
                self.apply_source(name)
        self.invalidate()

    def source_value(self, source: str) -> MeasurementValue:
        """Return the exact pair displayed in a linked input field."""
        result = self.saved_results[source][1]
        mean, error = result.mean, result.total_error
        if self.round_sources.isChecked():
            mean, error = round_measurement(mean, error)
        return MeasurementValue(mean, error)

    def toggle_steps(self, expanded: bool) -> None:
        """Show the optional numerical derivation without filling the main screen."""
        self.steps_output.setVisible(expanded)
        self.steps_toggle.setText("Скрыть ход расчёта" if expanded else "Показать ход расчёта / формулы подстановки")

    def apply_source(self, name: str) -> None:
        """Fill locked linked inputs using the selected rounding mode."""
        row = self.rows[name]
        source = row.source.currentData()
        linked = source in self.saved_results
        row.mean.setReadOnly(linked)
        row.error.setReadOnly(linked)
        row.unit.clear()
        if linked:
            unit, _ = self.saved_results[source]
            result = self.source_value(source)
            row.mean.setText(repr(result.mean))
            row.error.setText(repr(result.total_error))
            row.unit.setText(unit)
        self.invalidate()

    def inputs(self) -> dict:
        """Capture the formula and raw variable fields for diagnostics."""
        return {"formula": self.formula.text(), "name": self.name.text(), "unit": self.unit.text(), "round_sources": self.round_sources.isChecked(), "variables": {name: {"mean": row.mean.text(), "error": row.error.text(), "source": row.source.currentData()} for name, row in self.rows.items()}}

    def calculate(self) -> None:
        """Validate current fields and propagate uncertainties in the background."""
        inputs = self.inputs()
        try:
            formula = self.normalized_formula()
            if formula != self.parsed_formula:
                if self.parse_error is not None:
                    raise self.parse_error
                raise InvalidInputError("Дождитесь обновления полей переменных.")
            if not self.name.text().strip():
                raise InvalidInputError("Укажите символ результата.")
            variables = {}
            for name, row in self.rows.items():
                source = row.source.currentData()
                if source in self.saved_results:
                    variables[name] = self.source_value(source)
                else:
                    variables[name] = MeasurementValue(number(row.mean.text(), f"{name}: среднее"), number(row.error.text(), f"{name}: погрешность", True))
            self.pending = (self.revision, inputs)
            self.calculate_button.setEnabled(False)
            self.calculate_button.setText("Вычисление…")
            self.worker = CalculationWorker(lambda: calculate_indirect_measurement(formula, variables))
            self.worker.signals.succeeded.connect(self.show_result)
            self.worker.signals.failed.connect(self.calculation_failed)
            QThreadPool.globalInstance().start(self.worker)
        except Exception as exc:
            ErrorDialog(exc, inputs, self).exec()

    def finish(self) -> None:
        """Restore calculation controls after background work."""
        self.worker = None
        self.calculate_button.setText("Рассчитать")
        self.calculate_button.setEnabled(not self.parse_busy and not self.timer.isActive())

    def calculation_failed(self, error: Exception, stack: str) -> None:
        """Present engine diagnostics with the exact submitted input snapshot."""
        self.finish()
        ErrorDialog(error, self.pending[1], self, stack).exec()

    def show_result(self, result: IndirectMeasurementResult) -> None:
        """Display the rounded value and symbolic formulas supplied by the engine."""
        self.finish()
        if self.pending[0] != self.revision:
            return
        self.result_saved.emit(self.name.text().strip(), self.unit.text().strip(), MeasurementValue(result.value, result.total_error))
        self.result = result
        relative = f"ε = {display(result.relative_error_pct)} %" if result.value else "ε не определена при нулевом результате"
        self.card.setText(result_text(self.name.text().strip(), self.unit.text().strip(), result.value, result.total_error) + "\n" + relative)
        self.formula_output.setPlainText(f"F = {result.formula_latex}\n\n\\Delta F = {result.error_formula_latex}")
        self.steps_output.setPlainText(result.calculation_steps)
        self.steps_toggle.setEnabled(True)
        self.copy_text.setEnabled(True)
        self.copy_latex.setEnabled(True)

    def copy_result(self, latex: bool) -> None:
        """Copy either the final text or final result and uncertainty formula in LaTeX."""
        if self.result:
            text = result_text(self.name.text().strip(), self.unit.text().strip(), self.result.value, self.result.total_error, latex)
            if latex:
                text += f"\n\\Delta F = {self.result.error_formula_latex}"
            QApplication.clipboard().setText(text)
