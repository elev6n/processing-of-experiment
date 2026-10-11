"""Shared unit choices and live SI conversion hints."""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QWidget

from units_engine import Quantity, UNIT_REGISTRY, format_dimension


class UnitSelector(QComboBox):
    """Editable choices supporting validated compound SI units and legacy text APIs."""

    textChanged = Signal(str)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setMinimumContentsLength(6)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        common = ["", "1", "мм", "см", "м", "км", "мг", "г", "кг", "мкс", "мс", "с", "А", "К", "моль", "кд", "м/с", "м/с²", "Гц", "Н", "Дж", "Па", "В", "Вт", "Ом", "Па·с"]
        self.addItems(common + sorted(set(UNIT_REGISTRY) - set(common)))
        self.setCurrentText(text)
        self.currentTextChanged.connect(self.textChanged.emit)
        self.setToolTip("Выберите единицу или введите составную: кг*м**2/с**2. Расчёты выполняются в СИ.")

    def text(self) -> str:
        """Return the selected unit, preserving the existing widget interface."""
        return self.currentText()

    def setText(self, text: str) -> None:
        """Select a unit or a compound expression."""
        self.setCurrentText(text)

    def clear(self) -> None:
        """Reset the selected unit while retaining the available choices."""
        self.setCurrentText("")

    def setPlaceholderText(self, text: str) -> None:
        self.lineEdit().setPlaceholderText(text)


def update_si_hint(label: QLabel, unit: str, values: list[str]) -> None:
    """Preview input values in SI; incomplete input is harmless while typing."""
    try:
        previews = []
        for text in values:
            if text.strip():
                quantity = Quantity(float(text.replace(",", ".")), unit)
                previews.append(f"{quantity.to_si():.8g} {format_dimension(quantity.dimension)}")
        label.setText("СИ: " + "; ".join(previews) if previews else "СИ: выберите единицу и введите числа")
    except ValueError:
        label.setText("СИ: проверьте число и единицу")


def bind_si_hint(mean: QLineEdit, error: QLineEdit, unit: UnitSelector, label: QLabel) -> Callable[[], None]:
    """Update a row's conversion hint on every numerical or unit edit."""
    label.setWordWrap(True)
    def refresh() -> None:
        update_si_hint(label, unit.text(), [mean.text(), error.text()])
    mean.textChanged.connect(refresh)
    error.textChanged.connect(refresh)
    unit.textChanged.connect(refresh)
    refresh()
    return refresh
