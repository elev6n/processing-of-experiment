"""Headless integration checks for measurement input and linked calculations."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from calc_engine import FormulaParseError, calculate_direct_measurement, formula_variables, round_measurement
from main_window import MainWindow
from widgets.common import result_text
from widgets.error_dialog import ErrorDialog


@pytest.fixture(scope="module")
def app():
    """Keep a single QApplication alive for all Qt integration checks."""
    application = QApplication.instance() or QApplication([])
    yield application
    QThreadPool.globalInstance().waitForDone(5000)


@pytest.fixture
def window(app):
    """Create an independent main window for each workflow."""
    widget = MainWindow()
    yield widget
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def until(app, condition):
    """Process Qt events until a worker result is delivered or a deadline expires."""
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert condition(), "Qt operation did not finish within five seconds"


def direct_result(app, window):
    """Calculate the series shown in the reference notebook."""
    tab = window.direct_tab
    QApplication.clipboard().setText("19,89\n19,89\n19,87\n19,91\n19,89")
    tab.table.setCurrentCell(0, 1)
    tab.table.paste()
    tab.calculate()
    until(app, lambda: tab.result is not None)
    return tab.result


def test_notebook_table_and_invalidation(app, window):
    result = direct_result(app, window)
    tab = window.direct_tab
    assert result.mean == pytest.approx(19.89)
    assert tab.output_table.rowCount() == 5
    assert tab.output_table.rowSpan(0, 4) == 5
    assert tab.output_table.item(2, 3).text() == "0,0004"
    assert "19,890 ± 0,019" in tab.card.text()
    tab.copy_result(True)
    assert r"\pm" in QApplication.clipboard().text()
    tab.table.setItem(0, 1, QTableWidgetItem("20"))
    assert tab.result is None
    assert not tab.copy_text.isEnabled()
    assert "d" in tab.saved_results


@pytest.mark.parametrize("rounded", [True, False])
def test_linked_indirect_inputs_refresh_and_selected_precision(app, window, rounded):
    direct_result(app, window)
    tab = window.indirect_tab
    tab.round_sources.setChecked(rounded)
    tab.formula.setText("d^2 / 2")
    until(app, lambda: tab.parsed_formula == "d**2 / 2")
    row = tab.rows["d"]
    row.source.setCurrentIndex(row.source.findData("d"))
    assert row.mean.isReadOnly()
    assert float(row.mean.text()) == window.direct_tab.result.mean
    tab.calculate()
    until(app, lambda: tab.result is not None)
    assert tab.result.value == pytest.approx(19.89**2 / 2)
    error = window.direct_tab.result.total_error
    assert tab.result.total_error == pytest.approx(19.89 * (0.019 if rounded else error))
    window.direct_tab.table.setItem(0, 1, QTableWidgetItem("20"))
    window.direct_tab.calculate()
    until(app, lambda: window.direct_tab.result is not None)
    assert tab.result is None
    result = window.direct_tab.result
    expected = round_measurement(result.mean, result.total_error)[0] if rounded else result.mean
    assert float(row.mean.text()) == expected


def test_notebook_rounding_steps_and_chained_pool(app, window):
    direct = calculate_direct_measurement([2.5, 2.52, 2.37, 2.71, 2.81], 0.0131)
    window.save_result("t", "с", direct)
    tab = window.indirect_tab
    tab.name.setText("V")
    tab.unit.setText("м/с")
    tab.formula.setText("S/t")
    until(app, lambda: tab.parsed_formula == "S/t")
    tab.rows["S"].mean.setText("0.422")
    tab.rows["S"].error.setText("0.001")
    tab.rows["t"].source.setCurrentIndex(tab.rows["t"].source.findData("t"))
    assert tab.rows["t"].mean.text() == "2.58"
    assert tab.rows["t"].error.text() == "0.22"
    tab.calculate()
    until(app, lambda: tab.result is not None)
    velocity = tab.result
    assert velocity.value == pytest.approx(0.422 / 2.58)
    assert velocity.total_error == pytest.approx(((0.001 / 2.58)**2 + (0.422 * 0.22 / 2.58**2)**2)**0.5)
    assert velocity.input_values["t"].mean == 2.58
    assert "0.422 / 2.58" in tab.steps_output.toPlainText()
    assert "∂F/∂t" in tab.steps_output.toPlainText()
    assert tab.steps_output.isHidden()
    tab.steps_toggle.click()
    assert not tab.steps_output.isHidden()
    tab.copy_result(True)
    assert r"\Delta F" in QApplication.clipboard().text()
    assert "V" in window.saved_results
    tab.round_sources.setChecked(False)
    assert tab.result is None
    assert float(tab.rows["t"].mean.text()) == direct.mean
    assert float(tab.rows["t"].error.text()) == direct.total_error
    assert tab.steps_output.isHidden()
    assert not tab.steps_toggle.isEnabled()
    tab.round_sources.setChecked(True)

    tab.name.setText("K")
    tab.formula.setText("V**2/2")
    until(app, lambda: tab.parsed_formula == "V**2/2")
    row = tab.rows["V"]
    row.source.setCurrentIndex(row.source.findData("V"))
    assert row.mean.isReadOnly()
    assert float(row.mean.text()) == 0.164
    tab.calculate()
    until(app, lambda: tab.result is not None)
    assert tab.result.value == pytest.approx(0.164**2 / 2)
    assert "K" in window.saved_results
    window.direct_tab.name.setText("d")
    direct_result(app, window)
    assert {"t", "V", "K", "d"} <= window.saved_results.keys()
    assert tab.result is not None


def test_paste_invalid_column_is_atomic(app, window, monkeypatch):
    reports = []
    monkeypatch.setattr(ErrorDialog, "exec", lambda self: reports.append(self.report))
    table = window.direct_tab.table
    table.setItem(0, 1, QTableWidgetItem("12"))
    QApplication.clipboard().setText("1,5\nincorrect")
    table.paste()
    assert table.item(0, 1).text() == "12"
    assert table.item(1, 1) is None
    assert "incorrect" in reports[0]
    assert "Traceback" in reports[0]


def test_manual_inputs_domain_errors_and_diagnostics(app, window, monkeypatch):
    reports = []
    monkeypatch.setattr(ErrorDialog, "exec", lambda self: reports.append(self.report))
    tab = window.indirect_tab
    tab.formula.setText("sqrt(x)")
    until(app, lambda: tab.parsed_formula == "sqrt(x)")
    tab.rows["x"].mean.setText("4")
    tab.rows["x"].error.setText("0,2")
    tab.calculate()
    until(app, lambda: tab.result is not None)
    assert tab.result.value == 2
    assert tab.result.total_error == pytest.approx(0.05)
    tab.rows["x"].mean.setText("-1")
    tab.calculate()
    until(app, lambda: bool(reports))
    assert "MathDomainError" in reports[0]
    assert "Python:" in reports[0]
    assert "sqrt(x)" in reports[0]


def test_obsolete_parse_and_calculation_are_discarded(app, window):
    tab = window.indirect_tab
    tab.formula.setText("a+b")
    tab.timer.stop()
    tab.parse_formula()
    tab.formula.setText("c^2")
    until(app, lambda: tab.parsed_formula == "c**2")
    assert set(tab.rows) == {"c"}
    tab.rows["c"].mean.setText("2")
    tab.rows["c"].error.setText("0.1")
    tab.calculate()
    tab.rows["c"].mean.setText("3")
    until(app, lambda: tab.worker is None)
    assert tab.result is None
    assert not tab.copy_text.isEnabled()
    assert "F" not in window.saved_results


@pytest.mark.parametrize("formula,names", [("m*v**2/2", ["m", "v"]), ("sqrt(x)+sin(y)+pi", ["x", "y"]), ("x/x", ["x"]), ("2*pi", [])])
def test_safe_formula_discovery(formula, names):
    assert formula_variables(formula) == names


@pytest.mark.parametrize("formula", ["__import__('os')", "x.__class__", "x[0]", "sin(x,y)", "x + ("])
def test_formula_discovery_rejects_non_arithmetic(formula):
    with pytest.raises(FormulaParseError):
        formula_variables(formula)


def test_result_formatting_keeps_zeros_and_small_uncertainties():
    assert "19,890 ± 0,019" in result_text("d", "мм", 19.89, 0.018709)
    assert "10^-20" in result_text("x", "м", 1.2e-18, 1.2e-20)
    assert r"\_" in result_text("x_1", "м", 1, 0.1, True)
