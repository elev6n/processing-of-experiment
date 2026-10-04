"""Physical measurement calculations, symbolic propagation and final rounding.

Intermediate calculations retain floating-point precision; round only for display.
The detailed rounding rule in the requirements takes precedence: leading digits
1, 2 and 3 retain two significant digits. Both S_x fields follow the explicitly
specified standard deviation of the mean, rather than the sample deviation.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from numbers import Real
from typing import Any

import numpy as np
import sympy as sp
from scipy.stats import t
from sympy.parsing.sympy_parser import parse_expr


class InvalidInputError(ValueError):
    """Input data violate the measurement API's constraints."""


class FormulaParseError(ValueError):
    """A formula contains invalid syntax, unknown names or unsupported operations."""


class MathDomainError(ArithmeticError):
    """A calculation leaves the finite real domain."""


@dataclass
class DirectMeasurementResult:
    """Unrounded direct result and per-observation table, with errors in input units."""

    raw_data: list[float]
    n: int
    mean: float
    std_dev: float
    std_error: float
    t_student: float
    random_error: float
    instr_error: float
    total_error: float
    relative_error_pct: float
    table_rows: list[dict[str, float]]


@dataclass
class IndirectMeasurementResult:
    """Unrounded function value, independent-error propagation and LaTeX formulas."""

    formula_str: str
    value: float
    total_error: float
    relative_error_pct: float
    formula_latex: str
    error_formula_latex: str
    partials_eval: dict[str, float]


def _input_number(value: Any, name: str) -> float:
    """Return a finite real input or raise InvalidInputError."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise InvalidInputError(f"{name} must be a finite real number.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InvalidInputError(f"{name} is outside floating-point range.") from exc
    if not math.isfinite(result):
        raise InvalidInputError(f"{name} must be finite.")
    return result


def _real(value: Any, context: str) -> float:
    """Convert a calculated value to a finite real or raise MathDomainError."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MathDomainError(f"{context} is not a finite real value.") from exc
    if not math.isfinite(result):
        raise MathDomainError(f"{context} is not a finite real value.")
    return result


def _relative_error(value: float, error: float) -> float:
    """Return percentage error; a zero value has undefined (infinite) relative error."""
    return error / abs(value) * 100.0 if value else math.inf


def calculate_direct_measurement(
    measurements: Sequence[float], theta: float, alpha: float = 0.95
) -> DirectMeasurementResult:
    """Calculate the mean and combined uncertainty of repeated measurements.

    Args:
        measurements: Nonempty one-dimensional collection of finite real values.
        theta: Nonnegative absolute instrumental uncertainty.
        alpha: Confidence probability strictly between zero and one.

    Returns:
        Unrounded result. For one observation the Student coefficient and random
        uncertainty are zero. std_dev and std_error both store the specified S_x.

    Raises:
        InvalidInputError: Input values or confidence probability are invalid.
        MathDomainError: Computed values exceed the finite real domain.
    """
    theta = _input_number(theta, "theta")
    alpha = _input_number(alpha, "alpha")
    if theta < 0 or not 0 < alpha < 1:
        raise InvalidInputError("Require theta >= 0 and 0 < alpha < 1.")
    if not isinstance(measurements, (Sequence, np.ndarray)) or isinstance(
        measurements, (str, bytes)
    ):
        raise InvalidInputError("measurements must be a nonempty sequence.")
    if isinstance(measurements, np.ndarray) and measurements.ndim != 1:
        raise InvalidInputError("measurements must be one-dimensional.")
    raw_data = [_input_number(x, f"measurements[{i}]") for i, x in enumerate(measurements)]
    n = len(raw_data)
    if not n:
        raise InvalidInputError("At least one measurement is required.")
    data = np.asarray(raw_data, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        mean = _real(data[0] if np.all(data == data[0]) else np.sum(data / n), "Mean")
        differences = data - mean
        squares = differences**2
    if not np.all(np.isfinite(squares)):
        raise MathDomainError("Squared deviations exceed floating-point range.")
    std_error = math.hypot(*differences) / math.sqrt(n * (n - 1)) if n > 1 else 0.0
    coefficient = _real(t.ppf(1 - (1 - alpha) / 2, df=n - 1), "Student coefficient") if n > 1 else 0.0
    random_error = _real(coefficient * std_error, "Random uncertainty")
    total_error = _real(math.hypot(random_error, theta), "Total uncertainty")
    rows = [
        {"i": i + 1, "x": x, "diff": float(diff), "diff_sq": float(square)}
        for i, (x, diff, square) in enumerate(zip(raw_data, differences, squares))
    ]
    return DirectMeasurementResult(
        raw_data, n, mean, std_error, std_error, coefficient, random_error,
        theta, total_error, _relative_error(mean, total_error), rows,
    )


def _lg(value: sp.Expr) -> sp.Expr:
    """Return the base-ten logarithm of a symbolic or numeric value."""
    return sp.log(value, 10)


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "lg": _lg, "abs": sp.Abs,
}
_CONSTANTS: dict[str, Any] = {"pi": sp.pi, "E": sp.E}
_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def formula_variables(formula_str: str) -> list[str]:
    """Discover validated formula inputs using the engine's restricted SymPy parser.

    Preserve inputs of original operations even when symbolic simplification
    cancels them, so domain checks still receive their values.
    """
    if not formula_str.strip():
        raise FormulaParseError("Введите формулу.")
    if len(formula_str) > 1000:
        raise FormulaParseError("Формула должна содержать не более 1000 символов.")
    try:
        tree = ast.parse(formula_str.strip(), mode="eval").body
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise FormulaParseError("Проверьте скобки и операции в формуле.") from exc
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - set(_FUNCTIONS) - set(_CONSTANTS)
    if any(name.startswith("_") for name in names):
        raise FormulaParseError("Имена переменных не должны начинаться с подчёркивания.")
    _validate_formula(tree, names | set(_CONSTANTS))
    try:
        parse_expr(
            formula_str.strip(),
            local_dict={**_FUNCTIONS, **_CONSTANTS, **{name: sp.Symbol(name, real=True) for name in names}},
            global_dict={"__builtins__": {}, "Integer": sp.Integer, "Float": sp.Float},
        )
    except (TypeError, ValueError, SyntaxError) as exc:
        raise FormulaParseError("Не удалось разобрать формулу.") from exc
    return sorted(names)


def _validate_formula(node: ast.AST, names: set[str]) -> None:
    """Accept only arithmetic, known variables and supported one-argument functions."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        try:
            _input_number(node.value, "Formula constant")
        except InvalidInputError as exc:
            raise FormulaParseError("Formula constants must be finite real numbers.") from exc
    elif isinstance(node, ast.Name) and node.id in names:
        return
    elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        _validate_formula(node.left, names)
        _validate_formula(node.right, names)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate_formula(node.operand, names)
    elif (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS and len(node.args) == 1 and not node.keywords
    ):
        _validate_formula(node.args[0], names)
    else:
        raise FormulaParseError("Use arithmetic, supplied variables and supported functions only.")


def _evaluate_formula(node: ast.AST, values: dict[str, float]) -> float:
    """Evaluate each original operation so symbolic cancellation cannot hide domain errors."""
    try:
        if isinstance(node, ast.Constant):
            result = node.value
        elif isinstance(node, ast.Name):
            result = values[node.id]
        elif isinstance(node, ast.BinOp):
            result = _OPERATORS[type(node.op)](
                _evaluate_formula(node.left, values), _evaluate_formula(node.right, values)
            )
        elif isinstance(node, ast.UnaryOp):
            operand = _evaluate_formula(node.operand, values)
            result = -operand if isinstance(node.op, ast.USub) else operand
        else:
            # The validator guarantees that the remaining node is a supported call.
            assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            result = _FUNCTIONS[node.func.id](_evaluate_formula(node.args[0], values))
    except (ZeroDivisionError, OverflowError, ValueError) as exc:
        raise MathDomainError("Formula is undefined at the supplied means.") from exc
    return _real(result, "Formula operation")


def calculate_indirect_measurement(
    formula_str: str, variables_data: Mapping[str, DirectMeasurementResult]
) -> IndirectMeasurementResult:
    """Propagate independent absolute uncertainties through a real scalar formula.

    Args:
        formula_str: Python arithmetic using ** for powers; supports sqrt, sin,
            cos, tan, asin, acos, atan, exp, log/ln, lg, abs and constants pi/E.
        variables_data: Variable names mapped to direct results (mean, total_error).

    Returns:
        Function value, propagated uncertainty, evaluated partials and LaTeX.

    Raises:
        InvalidInputError: Variable data or means/uncertainties are invalid.
        FormulaParseError: Formula syntax, operations or variable names are invalid.
        MathDomainError: A function or derivative is not finite and real.
    """
    if not isinstance(formula_str, str) or not formula_str.strip():
        raise FormulaParseError("A nonempty formula string is required.")
    if not isinstance(variables_data, Mapping):
        raise InvalidInputError("variables_data must be a mapping.")
    symbols: dict[str, sp.Symbol] = {}
    means: dict[str, float] = {}
    errors: dict[str, float] = {}
    for name, result in variables_data.items():
        if (
            not isinstance(name, str) or not name.isidentifier() or name.startswith("_")
            or name in _FUNCTIONS or name in _CONSTANTS
        ):
            raise InvalidInputError(f"Invalid or reserved variable name: {name!r}.")
        if not isinstance(result, DirectMeasurementResult):
            raise InvalidInputError(f"{name} must contain a DirectMeasurementResult.")
        means[name] = _input_number(result.mean, f"{name}.mean")
        errors[name] = _input_number(result.total_error, f"{name}.total_error")
        if errors[name] < 0:
            raise InvalidInputError(f"{name}.total_error must be nonnegative.")
        symbols[name] = sp.Symbol(name, real=True)
    try:
        tree = ast.parse(formula_str.strip(), mode="eval").body
    except (SyntaxError, ValueError) as exc:
        raise FormulaParseError("Invalid formula syntax.") from exc
    _validate_formula(tree, set(symbols) | set(_CONSTANTS))
    local_dict = {**_FUNCTIONS, **_CONSTANTS, **symbols}
    try:
        expression = parse_expr(
            formula_str.strip(), local_dict=local_dict,
            global_dict={"__builtins__": {}, "Integer": sp.Integer, "Float": sp.Float},
        )
    except (TypeError, ValueError, SyntaxError) as exc:
        raise FormulaParseError("Unable to parse formula.") from exc
    value = _evaluate_formula(tree, {**{k: float(v) for k, v in _CONSTANTS.items()}, **means})
    substitutions = {symbols[name]: mean for name, mean in means.items()}
    partials: dict[str, float] = {}
    contributions: list[float] = []
    symbolic_terms: list[sp.Expr] = []
    for name, symbol in symbols.items():
        derivative = sp.diff(expression, symbol)
        partials[name] = _real(derivative.subs(substitutions), f"Derivative for {name}")
        contributions.append(_real(partials[name] * errors[name], f"Uncertainty for {name}"))
        symbolic_terms.append((derivative * sp.Symbol(f"Delta_{name}", nonnegative=True)) ** 2)
    total_error = _real(math.hypot(*contributions), "Propagated uncertainty")
    return IndirectMeasurementResult(
        formula_str, value, total_error, _relative_error(value, total_error),
        sp.latex(expression), sp.latex(sp.sqrt(sp.Add(*symbolic_terms))), partials,
    )


def round_measurement(mean: float, error: float) -> tuple[float, float]:
    """Round uncertainty and mean to a common decimal place, with half ties away from zero.

    Args:
        mean: Finite measured value.
        error: Finite nonnegative absolute uncertainty.

    Returns:
        (rounded_mean, rounded_error). Leading uncertainty digits 1, 2, 3 keep
        two significant digits; 4 through 9 keep one. Zero uncertainty leaves
        the mean unchanged. Floats do not preserve display trailing zeros.

    Raises:
        InvalidInputError: Values are invalid or uncertainty is negative.
        MathDomainError: A rounded result exceeds floating-point range.
    """
    mean = _input_number(mean, "mean")
    error = _input_number(error, "error")
    if error < 0:
        raise InvalidInputError("error must be nonnegative.")
    if error == 0:
        return mean, 0.0
    with localcontext() as context:
        context.prec = 800  # Covers the complete finite binary64 decimal range.
        uncertainty = Decimal(str(error))
        significant_digits = 2 if uncertainty.as_tuple().digits[0] <= 3 else 1
        place = uncertainty.adjusted() - significant_digits + 1
        rounded_error = uncertainty.quantize(Decimal(1).scaleb(place), rounding=ROUND_HALF_UP)
        # A carry (9.9 -> 10) moves the last significant digit to the next place.
        place = rounded_error.adjusted() - significant_digits + 1
        quantum = Decimal(1).scaleb(place)
        rounded_mean = Decimal(str(mean)).quantize(quantum, rounding=ROUND_HALF_UP)
    return _real(rounded_mean, "Rounded mean"), _real(rounded_error, "Rounded uncertainty")
