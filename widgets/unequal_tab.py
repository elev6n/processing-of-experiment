"""Combine manually entered series or any saved measurement results."""

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from calc_engine import (
    DirectMeasurementResult, InvalidInputError, MeasurementValue,
    UnequalMeasurementResult, calculate_unequal_measurements, round_measurement,
)
from widgets.common import CalculationWorker, display, number, numeric_edit, result_text
from widgets.error_dialog import ErrorDialog


class SeriesRow(QGroupBox):
    """One series with editable values or a saved measurement source."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = QComboBox()
        self.source.addItem("Ввести вручную", None)
        self.mean = numeric_edit()
        self.error = numeric_edit()
        self.unit = QLabel()
        self.remove_button = QPushButton("Удалить")
        layout = QHBoxLayout(self)
        for label, widget in [("Источник", self.source), ("Среднее x̄", self.mean), ("Погрешность Δx > 0", self.error)]:
            column = QFormLayout()
            column.addRow(label, widget)
            layout.addLayout(column)
        layout.addWidget(self.unit)
        layout.addWidget(self.remove_button)


class UnequalMeasurementTab(QWidget):
    """Calculate inverse-variance combinations and publish session snapshots."""

    result_saved = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[SeriesRow] = []
        self.saved_results: dict[str, tuple[str, DirectMeasurementResult | MeasurementValue]] = {}
        self.result: UnequalMeasurementResult | None = None
        self.revision = 0
        self.worker = None
        layout = QVBoxLayout(self)
        title = QLabel("Неравноточные измерения")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("Объедините независимые серии одной величины в одинаковых единицах. "
                      "Вес w = 1/Δx². Источник — сохранённый результат прямых, косвенных или неравноточных измерений.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        metadata = QGroupBox("Измеряемая величина")
        form = QFormLayout(metadata)
        self.name = QLineEdit("X")
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("Например: м/с²")
        form.addRow("Символ результата", self.name)
        form.addRow("Единица измерения", self.unit)
        layout.addWidget(metadata)
        self.round_sources = QCheckBox("Использовать округлённые значения сохранённых величин")
        self.round_sources.setChecked(True)
        self.round_sources.setToolTip("Включено: среднее и погрешность как в итоговой карточке. "
                                      "Выключено: полная сохранённая точность. Ручной ввод используется без изменений.")
        self.round_sources.toggled.connect(self.refresh_sources)
        layout.addWidget(self.round_sources)
        self.series_container = QWidget()
        self.series_layout = QVBoxLayout(self.series_container)
        self.series_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.series_container)
        self.add_button = QPushButton("Добавить серию")
        self.add_button.clicked.connect(self.add_series)
        layout.addWidget(self.add_button)
        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.setObjectName("primary")
        self.calculate_button.clicked.connect(self.calculate)
        layout.addWidget(self.calculate_button)
        output = QGroupBox("Веса серий и итоговый результат")
        output_layout = QVBoxLayout(output)
        self.output_table = QTableWidget(0, 6)
        self.output_table.setHorizontalHeaderLabels(["№ серии", "Источник", "Среднее x̄", "Погрешность Δx", "Вес w", "Вклад, %"])
        self.output_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.output_table.setAlternatingRowColors(True)
        self.output_table.verticalHeader().hide()
        self.output_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.output_table.setMinimumHeight(180)
        output_layout.addWidget(self.output_table)
        self.card = QLabel("Добавьте серии и нажмите «Рассчитать».")
        self.card.setObjectName("resultCard")
        self.card.setWordWrap(True)
        self.card.setTextFormat(Qt.TextFormat.PlainText)
        self.card.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_layout.addWidget(self.card)
        self.contribution_label = QLabel("Наибольший вклад будет выделен в таблице.")
        self.contribution_label.setWordWrap(True)
        output_layout.addWidget(self.contribution_label)
        self.steps_toggle = QPushButton("Показать ход расчёта / формулы подстановки")
        self.steps_toggle.setCheckable(True)
        self.steps_toggle.setEnabled(False)
        self.steps_toggle.toggled.connect(self.toggle_steps)
        output_layout.addWidget(self.steps_toggle)
        self.steps_output = QTextEdit()
        self.steps_output.setReadOnly(True)
        self.steps_output.setMinimumHeight(120)
        self.steps_output.setMaximumHeight(240)
        self.steps_output.hide()
        output_layout.addWidget(self.steps_output)
        buttons = QHBoxLayout()
        self.copy_text = QPushButton("Скопировать текст")
        self.copy_latex = QPushButton("Скопировать в LaTeX")
        self.copy_text.clicked.connect(lambda: self.copy_result(False))
        self.copy_latex.clicked.connect(lambda: self.copy_result(True))
        for button in [self.copy_text, self.copy_latex]:
            button.setEnabled(False)
            buttons.addWidget(button)
        output_layout.addLayout(buttons)
        layout.addWidget(output)
        layout.addStretch()
        self.name.textChanged.connect(self.invalidate)
        self.unit.textChanged.connect(self.invalidate)
        self.add_series()
        self.add_series()

    def invalidate(self, *_args) -> None:
        """Discard displayed output while retaining saved session snapshots."""
        self.revision += 1
        self.result = None
        self.output_table.setRowCount(0)
        self.card.setText("Данные изменены. Нажмите «Рассчитать».")
        self.contribution_label.clear()
        self.steps_output.clear()
        self.steps_toggle.setChecked(False)
        self.steps_toggle.setEnabled(False)
        self.copy_text.setEnabled(False)
        self.copy_latex.setEnabled(False)

    def add_series(self) -> None:
        """Append an independent editable series."""
        row = SeriesRow(self)
        self.rows.append(row)
        self.series_layout.addWidget(row)
        row.setTitle(f"Серия {len(self.rows)}")
        self.populate_source(row)
        row.mean.textChanged.connect(self.invalidate)
        row.error.textChanged.connect(self.invalidate)
        row.source.currentIndexChanged.connect(lambda _index: self.apply_source(row))
        row.remove_button.clicked.connect(lambda: self.remove_series(row))
        self.invalidate()

    def remove_series(self, row: SeriesRow) -> None:
        """Remove a series and keep visible numbering contiguous."""
        self.rows.remove(row)
        self.series_layout.removeWidget(row)
        row.deleteLater()
        for index, remaining in enumerate(self.rows, 1):
            remaining.setTitle(f"Серия {index}")
        self.invalidate()

    def populate_source(self, row: SeriesRow) -> None:
        """Refresh source choices without emitting selection changes."""
        selected = row.source.currentData()
        row.source.blockSignals(True)
        row.source.clear()
        row.source.addItem("Ввести вручную", None)
        for name, (unit, _) in self.saved_results.items():
            row.source.addItem(f"{name} ({unit})" if unit else name, name)
        row.source.setCurrentIndex(max(0, row.source.findData(selected)))
        row.source.blockSignals(False)

    def update_sources(self, results: dict) -> None:
        """Offer the entire session pool and refresh selected sources on replacement."""
        previous = self.saved_results
        self.saved_results = dict(results)
        for row in self.rows:
            selected = row.source.currentData()
            self.populate_source(row)
            if selected is not None and previous.get(selected) != self.saved_results.get(selected):
                self.apply_source(row)

    def source_value(self, source: str) -> MeasurementValue:
        """Return the selected precision pair used both in fields and calculation."""
        result = self.saved_results[source][1]
        mean, error = result.mean, result.total_error
        if self.round_sources.isChecked():
            mean, error = round_measurement(mean, error)
        return MeasurementValue(mean, error)

    def refresh_sources(self) -> None:
        """Apply the current precision mode to linked inputs only."""
        for row in self.rows:
            if row.source.currentData() in self.saved_results:
                self.apply_source(row)
        self.invalidate()

    def toggle_steps(self, expanded: bool) -> None:
        """Reveal or hide the numerical substitutions for the current result."""
        self.steps_output.setVisible(expanded)
        self.steps_toggle.setText("Скрыть ход расчёта" if expanded else "Показать ход расчёта / формулы подстановки")

    def apply_source(self, row: SeriesRow) -> None:
        """Fill and lock linked fields using the selected precision mode."""
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
        """Capture source labels and raw fields for worker diagnostics."""
        return {
            "name": self.name.text().strip(), "unit": self.unit.text().strip(),
            "round_sources": self.round_sources.isChecked(),
            "series": [{"source": row.source.currentData(), "mean": row.mean.text(), "error": row.error.text()} for row in self.rows],
        }

    def calculate(self) -> None:
        """Validate fields and compute an immutable input snapshot in the background."""
        if self.worker is not None:
            return
        inputs = self.inputs()
        try:
            if not inputs["name"]:
                raise InvalidInputError("Укажите символ результата.")
            if not self.rows:
                raise InvalidInputError("Добавьте хотя бы одну серию измерений.")
            series = []
            for index, row in enumerate(inputs["series"], 1):
                if row["source"] in self.saved_results:
                    series.append(self.source_value(row["source"]))
                else:
                    series.append(MeasurementValue(number(row["mean"], f"Серия {index}: среднее"),
                                                   number(row["error"], f"Серия {index}: погрешность")))
            self.pending = (self.revision, inputs)
            self.worker = CalculationWorker(lambda: calculate_unequal_measurements(series))
            self.worker.signals.succeeded.connect(self.show_result)
            self.worker.signals.failed.connect(self.calculation_failed)
            self.calculate_button.setEnabled(False)
            self.calculate_button.setText("Вычисление…")
            QThreadPool.globalInstance().start(self.worker)
        except Exception as exc:
            ErrorDialog(exc, inputs, self).exec()

    def finish(self) -> None:
        """Restore calculation controls when background work completes."""
        self.worker = None
        self.calculate_button.setEnabled(True)
        self.calculate_button.setText("Рассчитать")

    def calculation_failed(self, error: Exception, stack: str) -> None:
        """Show diagnostics only when they still refer to current inputs."""
        self.finish()
        if self.pending[0] == self.revision:
            ErrorDialog(error, self.pending[1], self, stack).exec()

    def show_result(self, result: UnequalMeasurementResult) -> None:
        """Render weights, highlight dominant series and publish the scalar result."""
        self.finish()
        revision, inputs = self.pending
        if revision != self.revision:
            return
        name, unit = inputs["name"], inputs["unit"]
        # Publish first: replacing a selected source can refresh linked inputs.
        # Render the successful submitted snapshot afterward.
        self.result_saved.emit(name, unit, MeasurementValue(result.mean, result.total_error))
        self.result = result
        self.output_table.setRowCount(len(result.series))
        largest = max(result.contributions)
        dominant = []
        for index, (entry, weight, contribution) in enumerate(zip(result.series, result.weights, result.contributions)):
            values = [str(index + 1), inputs["series"][index]["source"] or "Вручную",
                      display(entry.mean), display(entry.total_error), display(weight), display(100 * contribution)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if contribution == largest:
                    item.setBackground(QColor("#d5e6ff"))
                    item.setToolTip("Наибольший вклад в сумму весов")
                self.output_table.setItem(index, column, item)
            if contribution == largest:
                dominant.append(str(index + 1))
        relative = f"ε = {display(result.relative_error_pct)} %" if result.mean else "ε не определена при нулевом среднем"
        self.card.setText(result_text(name, unit, result.mean, result.total_error) + "\n" + relative)
        self.contribution_label.setText(f"Наибольший вклад: серии {', '.join(dominant)} — {display(100 * largest)} % каждая. "
                                        "Результат сохранён и доступен в косвенных измерениях.")
        precision = "округление как в итоговой карточке" if inputs["round_sources"] else "полная сохранённая точность"
        sources = "\n".join(f"Серия {index}: {row['source'] or 'ручной ввод'}" for index, row in enumerate(inputs["series"], 1))
        self.steps_output.setPlainText(f"Режим сохранённых источников: {precision}.\n"
                                      f"Ручной ввод используется без изменений.\n{sources}\n\n{result.calculation_steps}")
        self.steps_toggle.setEnabled(True)
        self.copy_text.setEnabled(True)
        self.copy_latex.setEnabled(True)

    def copy_result(self, latex: bool) -> None:
        """Copy the rounded result and relative uncertainty in the selected format."""
        if self.result is None:
            return
        text = result_text(self.name.text().strip(), self.unit.text().strip(), self.result.mean, self.result.total_error, latex)
        if self.result.mean:
            relative = display(self.result.relative_error_pct)
            text += rf"\quad \varepsilon_w = {relative}\%" if latex else f"\nε = {relative} %"
        else:
            text += r"\quad \text{Относительная погрешность не определена}" if latex else "\nε не определена при нулевом среднем"
        QApplication.clipboard().setText(text)
