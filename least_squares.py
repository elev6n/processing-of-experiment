"""Ordinary linear least squares, independent of the Qt interface."""

from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real

import numpy as np

from calc_engine import InvalidInputError, MathDomainError


@dataclass
class LeastSquaresResult:
    """Unrounded coefficients, one-sigma errors and plotting observations."""

    k: float
    b: float
    delta_k: float
    delta_b: float
    correlation: float | None
    residual_variance: float
    x: list[float]
    y: list[float]
    delta_x: list[float] | None
    delta_y: list[float] | None


def _array(values: Sequence[float], label: str) -> np.ndarray:
    if not isinstance(values, (Sequence, np.ndarray)) or isinstance(values, (str, bytes)):
        raise InvalidInputError(f"{label}: требуется одномерный массив чисел.")
    if isinstance(values, np.ndarray) and values.ndim != 1:
        raise InvalidInputError(f"{label}: требуется одномерный массив.")
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) for value in values):
        raise InvalidInputError(f"{label}: допускаются только конечные действительные числа.")
    try:
        result = np.asarray(values, dtype=float)
    except (ValueError, OverflowError) as exc:
        raise InvalidInputError(f"{label}: числа вне допустимого диапазона.") from exc
    if not np.all(np.isfinite(result)):
        raise InvalidInputError(f"{label}: числа должны быть конечными.")
    return result


def calculate_least_squares(
    x: Sequence[float], y: Sequence[float],
    delta_x: Sequence[float] | None = None, delta_y: Sequence[float] | None = None,
) -> LeastSquaresResult:
    """Fit y = k*x + b with residual-based standard errors.

    Require at least three paired finite observations and nonconstant X.
    Optional nonnegative per-point uncertainties are retained for error bars;
    ordinary least squares does not use them as weights. Errors are one-sigma
    estimates, without a Student multiplier. Constant Y has undefined Pearson r.

    Raises:
        InvalidInputError: Invalid observations or uncertainties.
        MathDomainError: Computed values exceed floating-point range.
    """
    xs, ys = _array(x, "X"), _array(y, "Y")
    n = len(xs)
    if n != len(ys) or n < 3:
        raise InvalidInputError("Нужны минимум три пары X, Y одинаковой длины.")
    errors = []
    for values, label in ((delta_x, "ΔX"), (delta_y, "ΔY")):
        error = None if values is None else _array(values, label)
        if error is not None and (len(error) != n or np.any(error < 0)):
            raise InvalidInputError(f"{label}: нужны N неотрицательных погрешностей.")
        errors.append(error)
    if np.all(xs == xs[0]):
        raise InvalidInputError("Все X совпадают: наклон прямой определить невозможно.")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
            # Subtract the first observation before averaging to preserve small
            # separations when the data have a large common offset.
            dx, dy = xs - xs[0], ys - ys[0]
            x_scale = np.max(np.abs(dx))
            y_scale = np.max(np.abs(dy)) or 1.0
            ux, uy = dx / x_scale, dy / y_scale
            mx, my = np.mean(ux), np.mean(uy)
            cx, cy = ux - mx, uy - my
            sxx, syy = np.dot(cx, cx), np.dot(cy, cy)
            slope = np.dot(cx, cy) / sxx
            k = slope * y_scale / x_scale
            x_mean, y_mean = xs[0] + mx * x_scale, ys[0] + my * y_scale
            b = y_mean - k * x_mean
            residual = cy - slope * cx
            sigma = np.sqrt(np.dot(residual, residual) / (n - 2)) * y_scale
            delta_k = (sigma / x_scale) / np.sqrt(sxx)
            delta_b = np.hypot(sigma / np.sqrt(n), delta_k * x_mean)
            variance = sigma * sigma
            correlation = float(np.clip(np.dot(cx, cy) / np.sqrt(sxx * syy), -1, 1)) if syy else None
            if not np.all(np.isfinite([k, b, delta_k, delta_b, variance])):
                raise FloatingPointError("Nonfinite fit")
    except FloatingPointError as exc:
        raise MathDomainError("МНК: численный диапазон превышен. Измените единицы исходных данных.") from exc
    return LeastSquaresResult(
        float(k), float(b), float(delta_k), float(delta_b), correlation, float(variance),
        xs.tolist(), ys.tolist(), *(None if error is None else error.tolist() for error in errors),
    )
