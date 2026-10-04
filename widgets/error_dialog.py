"""User-facing diagnostics with a copyable technical report."""

import json
import platform
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from calc_engine import FormulaParseError, InvalidInputError, MathDomainError


class ErrorDialog(QMessageBox):
    """Present a concise error and expandable platform/input/traceback details."""

    def __init__(self, error: Exception, inputs: dict, parent: QWidget | None = None, stack: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Не удалось выполнить действие")
        self.setIcon(QMessageBox.Icon.Warning)
        if isinstance(error, FormulaParseError):
            message = "Ошибка в формуле. Проверьте скобки, имена переменных и операции."
        elif isinstance(error, InvalidInputError):
            message = "Проверьте введённые числа и погрешности."
        elif isinstance(error, MathDomainError):
            message = "Формула или её производная не определена для этих значений."
        else:
            message = "Возникла непредвиденная ошибка. Скопируйте отчёт для диагностики."
        self.setText(message)
        self.setInformativeText(str(error))
        stack = stack or "".join(traceback.format_exception(error))
        self.report = f"OS: {platform.platform()}\nPython: {sys.version}\nInputs:\n{json.dumps(inputs, ensure_ascii=False, indent=2, default=str)}\n\n{stack}"
        self.setDetailedText(self.report)
        self.setStandardButtons(QMessageBox.StandardButton.Ok)
        copy = self.addButton("Скопировать отчёт об ошибке", QMessageBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.report))
