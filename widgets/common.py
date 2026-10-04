"""Shared numeric input, display formatting and background execution."""

import math
from collections.abc import Callable
from decimal import Decimal

from PySide6.QtCore import QObject, QRunnable, QRegularExpression, Signal, Slot
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit

from calc_engine import InvalidInputError, round_measurement


def number(text: str, label: str, nonnegative: bool = False) -> float:
    """Read a finite number accepting either decimal separator."""
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as exc:
        raise InvalidInputError(f"{label}: введите число (например, 19,89).") from exc
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise InvalidInputError(f"{label}: требуется конечное {'неотрицательное ' if nonnegative else ''}число.")
    return value


def numeric_edit(text: str = "", nonnegative: bool = False) -> QLineEdit:
    """Create a numeric editor with decimal comma and scientific notation support."""
    edit = QLineEdit(text)
    sign = r"\+?" if nonnegative else r"[+-]?"
    pattern = sign + r"(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?"
    edit.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), edit))
    edit.setPlaceholderText("0,00")
    return edit


def display(value: float) -> str:
    """Format intermediate values without premature rounding."""
    return format(value, ".8g").replace(".", ",")


def result_text(name: str, unit: str, value: float, error: float, latex: bool = False) -> str:
    """Format rounded results retaining significant trailing zeros."""
    rounded_value, rounded_error = round_measurement(value, error)
    if error:
        digits = 2 if Decimal(str(error)).as_tuple().digits[0] <= 3 else 1
        places = max(0, digits - 1 - Decimal(str(rounded_error)).adjusted())
        if places > 12:
            exponent = Decimal(str(rounded_error)).adjusted()
            scale = Decimal(10) ** exponent
            v = f"{Decimal(str(rounded_value)) / scale:.{digits - 1}f}"
            e = f"{Decimal(str(rounded_error)) / scale:.{digits - 1}f}"
            factor = rf"\cdot 10^{{{exponent}}}" if latex else f" × 10^{exponent}"
        else:
            v, e = f"{rounded_value:.{places}f}", f"{rounded_error:.{places}f}"
            factor = ""
    else:
        v, e, factor = format(value, ".8g"), "0", ""
    if latex:
        replacements = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#", "$": r"\$", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}
        escape = lambda text: "".join(replacements.get(char, char) for char in text)
        return rf"\text{{{escape(name)}}} = ({v} \pm {e}){factor}\,\text{{{escape(unit)}}}"
    return f"{name} = ({v} ± {e}){factor} {unit}".strip().replace(".", ",")


class WorkerSignals(QObject):
    """Deliver worker outcomes to the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(object, str)


class CalculationWorker(QRunnable):
    """Execute a calculation without accessing any Qt widgets."""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        """Emit either the result or an exception with its full traceback."""
        import traceback

        try:
            result = self.operation()
        except Exception as exc:
            self.signals.failed.emit(exc, traceback.format_exc())
        else:
            self.signals.succeeded.emit(result)
