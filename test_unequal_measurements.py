"""Reference calculations and validation for combining independent series."""

import math

import pytest

from calc_engine import (
    InvalidInputError, MathDomainError, MeasurementValue,
    calculate_direct_measurement, calculate_unequal_measurements,
)


def test_inverse_variance_reference() -> None:
    """Errors 1 and 2 yield contributions 80% and 20%."""
    result = calculate_unequal_measurements([MeasurementValue(10, 1), MeasurementValue(20, 2)])
    assert result.mean == pytest.approx(12)
    assert result.total_error == pytest.approx(2 / math.sqrt(5))
    assert result.relative_error_pct == pytest.approx(100 / (6 * math.sqrt(5)))
    assert result.weights == [1, 0.25]
    assert result.contributions == pytest.approx([0.8, 0.2])
    assert "w_1 = 1/Δx_1² = 1/(1.0)² = 1.0" in result.calculation_steps
    assert "Σw = 1.0 + 0.25 = 1.25" in result.calculation_steps
    assert "Σ(w·x̄) = (1.0 × 10.0) + (0.25 × 20.0) = 15.000" in result.calculation_steps
    assert "X̄_w = Σ(w·x̄)/Σw" in result.calculation_steps
    assert "ε_w = ΔX̄_w/|X̄_w|" in result.calculation_steps


def test_single_direct_result_is_copied() -> None:
    """One series retains its original precision and does not alias the source."""
    source = calculate_direct_measurement([1.23456789], 0.0123456789)
    result = calculate_unequal_measurements([source])
    assert result.mean == source.mean
    assert result.total_error == source.total_error
    source.mean = 42
    assert result.series[0].mean == 1.23456789


def test_equal_weights_and_zero_mean() -> None:
    """Equal uncertainties reduce by sqrt(K); relative error at zero is undefined."""
    result = calculate_unequal_measurements([MeasurementValue(-3, 2), MeasurementValue(3, 2)])
    assert result.mean == 0
    assert result.total_error == pytest.approx(math.sqrt(2))
    assert result.contributions == [0.5, 0.5]
    assert math.isinf(result.relative_error_pct)
    assert "ε_w не определена при нулевом среднем" in result.calculation_steps


@pytest.mark.parametrize("series", [
    None, [], "123", [1], [MeasurementValue(True, 1)],
    [MeasurementValue(math.nan, 1)], [MeasurementValue(1, math.inf)],
    [MeasurementValue(1, 0)], [MeasurementValue(1, -1)],
    [MeasurementValue(1, "0.1")], [MeasurementValue(1, True)],
])
def test_invalid_series(series) -> None:
    """All invalid data raise the application's public input exception."""
    with pytest.raises(InvalidInputError):
        calculate_unequal_measurements(series)


@pytest.mark.parametrize("error", [5e-324, 1e-200, 1e200, 1e308])
def test_unrepresentable_weight(error: float) -> None:
    """Do not display infinite or silently zero weights."""
    with pytest.raises(MathDomainError):
        calculate_unequal_measurements([MeasurementValue(1, error)])


def test_large_values_and_weight_sum_do_not_overflow() -> None:
    """Normalizing before summation preserves representable weighted results."""
    result = calculate_unequal_measurements([MeasurementValue(1e308, 1e-154)] * 3)
    assert result.mean == pytest.approx(1e308)
    assert result.total_error == pytest.approx(1e-154 / math.sqrt(3), abs=0)
    assert sum(result.contributions) == pytest.approx(1)
