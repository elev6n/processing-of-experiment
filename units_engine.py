"""SI units, conversions and dimension checking independent of the UI."""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from numbers import Real

import sympy as sp


class InvalidUnitError(ValueError):
    """An unknown unit or an incompatible physical dimension was supplied."""


@dataclass(frozen=True)
class Dimension:
    """Powers of SI bases in order L, M, T, I, temperature, amount, luminosity."""

    powers: tuple[Fraction, ...] = (Fraction(0),) * 7

    def __mul__(self, other: Dimension) -> Dimension:
        return Dimension(tuple(a + b for a, b in zip(self.powers, other.powers)))

    def __truediv__(self, other: Dimension) -> Dimension:
        return self * (other ** Fraction(-1))

    def __pow__(self, power: Fraction) -> Dimension:
        return Dimension(tuple(a * power for a in self.powers))


DIMENSIONLESS = Dimension()
L, M, T, I, TEMPERATURE, AMOUNT, LUMINOSITY = (
    Dimension(tuple(Fraction(int(i == j)) for i in range(7))) for j in range(7)
)
PREFIXES: dict[str, float] = {
    "н": 1e-9, "мк": 1e-6, "м": 1e-3, "с": 1e-2, "д": 1e-1,
    "": 1.0, "к": 1e3, "М": 1e6,
}


@dataclass(frozen=True)
class PhysicalUnit:
    """Input symbol, SI multiplier and physical dimension."""

    symbol: str
    multiplier: float
    dimension: Dimension


_BASES = {"м": L, "кг": M, "с": T, "А": I, "К": TEMPERATURE, "моль": AMOUNT, "кд": LUMINOSITY}
DERIVED_UNITS: dict[str, Dimension] = {
    "Гц": DIMENSIONLESS / T, "Н": M * L / T**Fraction(2),
    "Па": M / L / T**Fraction(2), "Дж": M * L**Fraction(2) / T**Fraction(2),
    "Вт": M * L**Fraction(2) / T**Fraction(3), "Кл": I * T,
    "В": M * L**Fraction(2) / T**Fraction(3) / I,
    "Ом": M * L**Fraction(2) / T**Fraction(3) / I**Fraction(2),
    "Ф": I**Fraction(2) * T**Fraction(4) / M / L**Fraction(2),
    "Тл": M / T**Fraction(2) / I, "Вб": M * L**Fraction(2) / T**Fraction(2) / I,
}
UNIT_REGISTRY: dict[str, PhysicalUnit] = {
    "1": PhysicalUnit("1", 1.0, DIMENSIONLESS), "рад": PhysicalUnit("рад", 1.0, DIMENSIONLESS),
}
for _symbol, _dimension in {**_BASES, **DERIVED_UNITS, "г": M}.items():
    if _symbol == "кг":
        UNIT_REGISTRY[_symbol] = PhysicalUnit(_symbol, 1.0, _dimension)
        continue
    for _prefix, _factor in PREFIXES.items():
        _name = _prefix + _symbol
        UNIT_REGISTRY[_name] = PhysicalUnit(_name, _factor * (1e-3 if _symbol == "г" else 1), _dimension)
_ALIASES = {
    "m": "м", "kg": "кг", "g": "г", "s": "с", "A": "А", "K": "К",
    "mol": "моль", "cd": "кд", "Hz": "Гц", "N": "Н", "Pa": "Па", "J": "Дж",
    "W": "Вт", "C": "Кл", "V": "В", "ohm": "Ом", "F": "Ф", "T": "Тл", "Wb": "Вб", "rad": "рад",
}
for _alias, _symbol in _ALIASES.items():
    UNIT_REGISTRY[_alias] = UNIT_REGISTRY[_symbol]
    if _alias not in ("kg", "rad"):
        for _prefix, _ru in {"n": "н", "u": "мк", "µ": "мк", "μ": "мк", "m": "м", "c": "с", "d": "д", "k": "к", "M": "М"}.items():
            UNIT_REGISTRY[_prefix + _alias] = UNIT_REGISTRY[_ru + _symbol]


def format_dimension(dimension: Dimension, derived: bool = True) -> str:
    """Format a dimension in SI bases or a recognized derived symbol."""
    if derived:
        for symbol, known in DERIVED_UNITS.items():
            if dimension == known:
                return symbol
        if dimension == DERIVED_UNITS["Па"] * T:
            return "Па·с"
    def term(symbol: str, power: Fraction) -> str:
        if power == 1:
            return symbol
        if power in (2, 3):
            return symbol + ("²" if power == 2 else "³")
        return f"{symbol}^({power})"
    numerator = [term(symbol, power) for symbol, power in zip(_BASES, dimension.powers) if power > 0]
    denominator = [term(symbol, -power) for symbol, power in zip(_BASES, dimension.powers) if power < 0]
    result = "·".join(numerator) or "1"
    if denominator:
        divisor = "·".join(denominator)
        result += "/" + (f"({divisor})" if len(denominator) > 1 else divisor)
    return result


def parse_unit(text: str) -> PhysicalUnit:
    """Parse registered symbols and compound products, ratios and rational powers safely."""
    normalized = text.strip() or "1"
    if len(normalized) > 200:
        raise InvalidUnitError("Единица должна содержать не более 200 символов.")
    normalized = normalized.replace("·", "*").replace("²", "**2").replace("³", "**3").replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval").body
        def visit(node: ast.AST) -> PhysicalUnit:
            if isinstance(node, ast.Name) and node.id in UNIT_REGISTRY:
                return UNIT_REGISTRY[node.id]
            if isinstance(node, ast.Constant) and type(node.value) is int and node.value == 1:
                return UNIT_REGISTRY["1"]
            if isinstance(node, ast.BinOp):
                left = visit(node.left)
                if isinstance(node.op, ast.Pow):
                    power = _constant_power(node.right)
                    if abs(power) > 100:
                        raise InvalidUnitError("Степень единицы должна быть в диапазоне от −100 до 100.")
                    return PhysicalUnit(text, left.multiplier ** float(power), left.dimension ** power)
                right = visit(node.right)
                if isinstance(node.op, ast.Mult):
                    return PhysicalUnit(text, left.multiplier * right.multiplier, left.dimension * right.dimension)
                if isinstance(node.op, ast.Div):
                    return PhysicalUnit(text, left.multiplier / right.multiplier, left.dimension / right.dimension)
            raise InvalidUnitError(f"Неизвестная единица «{text}». Выберите единицу СИ или задайте произведение / отношение.")
        unit = visit(tree)
        if not math.isfinite(unit.multiplier) or unit.multiplier <= 0:
            raise InvalidUnitError("Множитель единицы выходит за допустимый диапазон.")
        return PhysicalUnit(text, unit.multiplier, unit.dimension)
    except InvalidUnitError:
        raise
    except (SyntaxError, ValueError, OverflowError, ZeroDivisionError, RecursionError) as exc:
        raise InvalidUnitError(f"Некорректная единица «{text}».") from exc


def _constant_power(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _constant_power(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _constant_power(node.left) / _constant_power(node.right)
    raise InvalidUnitError("Степень размерной величины должна быть постоянным числом.")


@dataclass(frozen=True)
class Quantity:
    """A numerical value with its original input unit."""

    value: float
    unit: str = ""

    def to_si(self) -> float:
        """Return the finite value converted to SI."""
        if isinstance(self.value, bool) or not isinstance(self.value, Real) or not math.isfinite(self.value):
            raise InvalidUnitError("Значение величины должно быть конечным действительным числом.")
        result = self.value * parse_unit(self.unit).multiplier
        if not math.isfinite(result) or (self.value != 0 and result == 0):
            raise InvalidUnitError("После перевода в СИ число выходит за допустимый диапазон.")
        return result

    @property
    def dimension(self) -> Dimension:
        return parse_unit(self.unit).dimension

    @property
    def multiplier(self) -> float:
        return parse_unit(self.unit).multiplier


def formula_dimension(formula: str, units: Mapping[str, str]) -> Dimension:
    """Check original operations before SymPy simplification can cancel invalid sums."""
    dimensions = {name: parse_unit(unit).dimension for name, unit in units.items()}
    def visit(node: ast.AST) -> Dimension:
        if isinstance(node, ast.Constant):
            return DIMENSIONLESS
        if isinstance(node, ast.Name):
            if node.id in ("pi", "E"):
                return DIMENSIONLESS
            if node.id not in dimensions:
                raise InvalidUnitError(f"Не указана единица переменной {node.id}.")
            return dimensions[node.id]
        if isinstance(node, ast.UnaryOp):
            return visit(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if left != right:
                    raise InvalidUnitError(f"Нельзя складывать или вычитать {format_dimension(left)} и {format_dimension(right)}.")
                return left
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                if right != DIMENSIONLESS:
                    raise InvalidUnitError("Показатель степени должен быть безразмерным.")
                return DIMENSIONLESS if left == DIMENSIONLESS else left ** _constant_power(node.right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1:
            argument = visit(node.args[0])
            if node.func.id == "sqrt":
                # SymPy's exact Rational keeps fractional dimensions exact.
                return argument ** Fraction(str(sp.Rational(1, 2)))
            if node.func.id == "abs":
                return argument
            if argument != DIMENSIONLESS:
                raise InvalidUnitError(f"Аргумент {node.func.id} должен быть безразмерным.")
            return DIMENSIONLESS
        raise InvalidUnitError("Невозможно определить размерность этой операции.")
    try:
        return visit(ast.parse(formula.strip(), mode="eval").body)
    except (SyntaxError, RecursionError, ZeroDivisionError, OverflowError) as exc:
        raise InvalidUnitError("Не удалось определить размерность формулы.") from exc
