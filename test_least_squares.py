"""Regression accuracy and boundary conditions against independent references."""

import numpy as np
import pytest
from scipy.stats import linregress

from calc_engine import InvalidInputError, MathDomainError
from least_squares import calculate_least_squares


def test_fit_matches_scipy_with_residual_uncertainties():
    x = [1, 2, 4, 5, 8]
    y = [2, 5, 7, 11, 14]
    expected = linregress(x, y)
    actual = calculate_least_squares(x, y, [0.1] * 5, [0.2] * 5)
    assert actual.k == pytest.approx(expected.slope)
    assert actual.b == pytest.approx(expected.intercept)
    assert actual.delta_k == pytest.approx(expected.stderr)
    assert actual.delta_b == pytest.approx(expected.intercept_stderr)
    assert actual.correlation == pytest.approx(expected.rvalue)
    assert actual.residual_variance == pytest.approx(
        sum((yi - expected.slope * xi - expected.intercept) ** 2 for xi, yi in zip(x, y)) / 3
    )
    assert actual.delta_x == [0.1] * 5
    assert actual.delta_y == [0.2] * 5
    assert calculate_least_squares(x, y).k == actual.k


def test_exact_negative_slope_and_constant_y():
    fit = calculate_least_squares([0, 1, 2], [7, 5, 3])
    assert (fit.k, fit.b, fit.delta_k, fit.delta_b, fit.correlation) == (-2, 7, 0, 0, -1)
    constant = calculate_least_squares([0, 1, 2], [4, 4, 4])
    assert (constant.k, constant.b, constant.delta_k, constant.delta_b) == (0, 4, 0, 0)
    assert constant.correlation is None


def test_large_x_offset_and_unrounded_snapshot():
    x = np.array([1e12, 1e12 + 1, 1e12 + 2])
    fit = calculate_least_squares(x, [1, 3, 5])
    assert fit.k == 2
    assert fit.b == 1 - 2e12
    x[0] = 0
    assert fit.x[0] == 1e12


@pytest.mark.parametrize("x,y,dx,dy", [
    ([], [], None, None),
    ([1, 2], [1, 2], None, None),
    ([1, 2, 3], [1, 2], None, None),
    ([1, 1, 1], [1, 2, 3], None, None),
    ([1, 2, float("nan")], [1, 2, 3], None, None),
    ([1, 2, 3], [1, float("inf"), 3], None, None),
    ([True, 2, 3], [1, 2, 3], None, None),
    ([[1], [2], [3]], [1, 2, 3], None, None),
    (np.ones((3, 1)), [1, 2, 3], None, None),
    ([1, 2, 3], [1, 2, 3], [0.1], None),
    ([1, 2, 3], [1, 2, 3], None, [-1, 0, 0]),
    ([1, 2, 3], [1, 2, 3], None, [0, float("inf"), 0]),
])
def test_invalid_inputs(x, y, dx, dy):
    with pytest.raises(InvalidInputError):
        calculate_least_squares(x, y, dx, dy)


def test_zero_errors_and_numeric_overflow():
    assert calculate_least_squares([0, 1, 2], [0, 1, 2], [0] * 3).delta_x == [0] * 3
    with pytest.raises(MathDomainError):
        calculate_least_squares([-1e308, 0, 1e308], [0, 1, 2])
