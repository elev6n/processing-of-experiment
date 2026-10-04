"""Unit tests for the requested calc_endine module.

Run: python -m pytest test_calc_engine.py --cov=calc_endine --cov-report=term-missing
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np
import pytest
import sympy as sp

import calc_engine as engine
from calc_engine import (
    FormulaParseError,
    InvalidInputError,
    MathDomainError,
    calculate_direct_measurement,
    calculate_indirect_measurement,
    round_measurement,
)


def test_direct_statistics_and_table() -> None:
    """Check known Student value, all statistics and the observation table."""
    result = calculate_direct_measurement([1, 2, 3], theta=0.1)
    expected_sem = math.sqrt(1 / 3)
    assert result.raw_data == [1.0, 2.0, 3.0]
    assert result.n == 3
    assert result.mean == 2
    assert result.std_dev == pytest.approx(expected_sem)
    assert result.std_error == pytest.approx(expected_sem)
    assert result.t_student == pytest.approx(4.302652729696142)
    assert result.random_error == pytest.approx(4.302652729696142 * expected_sem)
    assert result.instr_error == 0.1
    assert result.total_error == pytest.approx(math.hypot(result.random_error, 0.1))
    assert result.relative_error_pct == pytest.approx(result.total_error / 2 * 100)
    assert result.table_rows == [
        {"i": 1, "x": 1, "diff": -1, "diff_sq": 1},
        {"i": 2, "x": 2, "diff": 0, "diff_sq": 0},
        {"i": 3, "x": 3, "diff": 1, "diff_sq": 1},
    ]


@pytest.mark.parametrize("data", [[-5], [-5, -5, -5], [0.123456789] * 7])
def test_direct_single_and_identical(data: list[float]) -> None:
    """Instrument uncertainty remains when observations have no scatter."""
    result = calculate_direct_measurement(data, 0.2)
    assert result.mean == data[0]
    assert result.std_dev == result.std_error == result.random_error == 0
    assert result.total_error == 0.2
    assert result.relative_error_pct == pytest.approx(0.2 / abs(data[0]) * 100)
    if len(data) == 1:
        assert result.t_student == 0


def test_confidence_probability_changes_student_coefficient() -> None:
    """Coefficients depend on both confidence probability and sample size."""
    low = calculate_direct_measurement([1, 2], 0, 0.9)
    high = calculate_direct_measurement([1, 2], 0, 0.99)
    assert low.t_student == pytest.approx(6.3137515148)
    assert high.t_student > low.t_student
    assert high.total_error > low.total_error


@pytest.mark.parametrize("data", [(1, 2), np.array([1, 2], dtype=float)])
def test_direct_accepts_sequences_without_mutation(data: Any) -> None:
    """Tuples and NumPy arrays are accepted and data are copied."""
    result = calculate_direct_measurement(data, 0)
    result.raw_data[0] = 100
    assert data[0] == 1
    assert result.mean == 1.5


@pytest.mark.parametrize("error", [0, 1])
def test_zero_mean_relative_error(error: float) -> None:
    """Relative uncertainty is undefined when the measured value is zero."""
    assert math.isinf(calculate_direct_measurement([0], error).relative_error_pct)


@pytest.mark.parametrize(
    "data,theta,alpha",
    [
        ([], 0, 0.95), (None, 0, 0.95), ("123", 0, 0.95),
        (np.array(1), 0, 0.95), (np.array([[1, 2]]), 0, 0.95),
        ([1], -1, 0.95), ([1], 0, 0), ([1], 0, 1),
        ([1], 0, -0.1), ([1], 0, 1.1), ([1], 0, math.nan),
        ([math.inf], 0, 0.95), ([math.nan], 0, 0.95),
        (["1"], 0, 0.95), ([True], 0, 0.95), ([np.bool_(True)], 0, 0.95),
        ([1j], 0, 0.95), ([1], math.inf, 0.95), ([1], True, 0.95),
        ([10**1000], 0, 0.95),
    ],
)
def test_invalid_direct_input(data: Any, theta: Any, alpha: Any) -> None:
    """Reject missing, nonnumeric, nonfinite and out-of-range inputs."""
    with pytest.raises(InvalidInputError):
        calculate_direct_measurement(data, theta, alpha)


def test_direct_overflow_is_domain_error() -> None:
    """An overflowing deviations table must not silently contain infinity."""
    with pytest.raises(MathDomainError):
        calculate_direct_measurement([-1e308, 1e308], 0)


def test_unrepresentable_student_probability_is_domain_error() -> None:
    """Confidence so close to one that the quantile becomes infinite is rejected."""
    with pytest.raises(MathDomainError):
        calculate_direct_measurement([1, 2], 0, math.nextafter(1, 0))


def test_kinetic_energy_and_latex() -> None:
    """Check the kinetic energy gradient and independent-error propagation."""
    result = calculate_indirect_measurement(
        "m * v**2 / 2",
        {"m": calculate_direct_measurement([2], 0.1),
         "v": calculate_direct_measurement([3], 0.2)},
    )
    assert result.formula_str == "m * v**2 / 2"
    assert result.value == 9
    assert result.partials_eval == {"m": 4.5, "v": 6}
    assert result.total_error == pytest.approx(math.hypot(0.45, 1.2))
    assert result.relative_error_pct == pytest.approx(result.total_error / 9 * 100)
    assert result.formula_latex == r"\frac{m v^{2}}{2}"
    m, v = sp.symbols("m v", real=True)
    dm, dv = sp.symbols("Delta_m Delta_v", nonnegative=True)
    assert result.error_formula_latex == sp.latex(sp.sqrt((v**2 * dm / 2)**2 + (m * v * dv)**2))


def test_product_and_unused_variable() -> None:
    """All supplied partials are returned, including zero for unused variables."""
    data = {name: calculate_direct_measurement([value], error)
            for name, value, error in [("a", 2, 0.1), ("b", 3, 0.2), ("c", 4, 0.3), ("d", 1, 1)]}
    result = calculate_indirect_measurement("a*b*c", data)
    assert result.value == 24
    assert result.partials_eval == {"a": 12, "b": 8, "c": 6, "d": 0}
    assert result.total_error == pytest.approx(math.sqrt(1.2**2 + 1.6**2 + 1.8**2))


@pytest.mark.parametrize(
    "formula,x,value,derivative",
    [
        ("sqrt(x)", 4, 2, 0.25), ("sin(x)", 0, 0, 1),
        ("cos(x)", 0, 1, 0), ("tan(x)", 0, 0, 1),
        ("asin(x)", 0, 0, 1), ("acos(x)", 0, math.pi / 2, -1),
        ("atan(x)", 0, 0, 1), ("exp(x)", 1, math.e, math.e),
        ("log(x)", math.e, 1, 1 / math.e), ("ln(x)", math.e, 1, 1 / math.e),
        ("lg(x)", 10, 1, 1 / (10 * math.log(10))), ("abs(x)", -2, 2, -1),
        ("-x + +2", 3, -1, -1), ("x - 2", 3, 1, 1),
        ("x/2", 3, 1.5, 0.5), ("x**-2", 2, 0.25, -0.25),
        ("x + pi + E", 1, 1 + math.pi + math.e, 1),
        ("x + 0.5", 1, 1.5, 1),
    ],
)
def test_supported_formulas(formula: str, x: float, value: float, derivative: float) -> None:
    """Supported operations evaluate correctly and propagate the analytic derivative."""
    result = calculate_indirect_measurement(formula, {"x": calculate_direct_measurement([x], 0.1)})
    assert result.value == pytest.approx(value)
    assert result.partials_eval["x"] == pytest.approx(derivative)
    assert result.total_error == pytest.approx(abs(derivative) * 0.1)


@pytest.mark.parametrize("formula,value", [("2", 2), ("0", 0), (" pi ", math.pi)])
def test_constant_formula(formula: str, value: float) -> None:
    """A constant formula requires no measurements and has zero absolute uncertainty."""
    result = calculate_indirect_measurement(formula, {})
    assert result.value == pytest.approx(value)
    assert result.total_error == 0
    assert result.partials_eval == {}
    assert result.error_formula_latex == "0"
    assert result.relative_error_pct == (math.inf if value == 0 else 0)


@pytest.mark.parametrize(
    "formula",
    ["", " ", None, "x +", "unknown + 1", "x ^ 2", "x // 2", "x % 2",
     "x.attr", "x[0]", "[x]", "True", "'x'", "sqrt(x, 2)", "sqrt(x=x)",
     "__import__('os').system('echo forbidden')", "(lambda: 1)()", "foo(x)", "1e309"],
)
def test_rejects_unsupported_or_unsafe_formulas(formula: Any) -> None:
    """Only the documented scalar arithmetic syntax reaches SymPy's parser."""
    with pytest.raises(FormulaParseError):
        calculate_indirect_measurement(formula, {"x": calculate_direct_measurement([1], 0.1)})


@pytest.mark.parametrize("name", [1, "x-y", "_private", "sqrt", "pi", "E"])
def test_invalid_variable_names(name: Any) -> None:
    """Names must be identifiers and may not shadow functions or constants."""
    with pytest.raises(InvalidInputError):
        calculate_indirect_measurement("1", {name: calculate_direct_measurement([1], 0)})


@pytest.mark.parametrize("data", [None, [], {"x": 1}])
def test_invalid_variable_mapping(data: Any) -> None:
    """Reject nonmapping inputs and values that are not direct measurement results."""
    with pytest.raises(InvalidInputError):
        calculate_indirect_measurement("x", data)


@pytest.mark.parametrize("field,value", [("mean", math.nan), ("mean", 1j), ("total_error", -1), ("total_error", math.inf)])
def test_invalid_direct_result_fields(field: str, value: Any) -> None:
    """Validate results supplied by callers, including manually modified dataclasses."""
    invalid = replace(calculate_direct_measurement([1], 0), **{field: value})
    with pytest.raises(InvalidInputError):
        calculate_indirect_measurement("x", {"x": invalid})


@pytest.mark.parametrize(
    "formula,x",
    [("1/x", 0), ("x/x", 0), ("0*(1/x)", 0), ("x**-1", 0),
     ("sqrt(x)", -1), ("log(x)", -1), ("log(x)", 0), ("acos(x)", 2),
     ("sqrt(x)", 0), ("exp(x)", 1000), ("x**2", 1e308)],
)
def test_indirect_domain_errors(formula: str, x: float) -> None:
    """Reject undefined original operations, complex results and singular derivatives."""
    with pytest.raises(MathDomainError):
        calculate_indirect_measurement(formula, {"x": calculate_direct_measurement([x], 0.1)})


def test_uncertainty_overflow_is_domain_error() -> None:
    """Finite means cannot conceal overflowing error propagation."""
    with pytest.raises(MathDomainError):
        calculate_indirect_measurement("2*x", {"x": calculate_direct_measurement([1], 1e308)})


def test_parser_failure_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A library parser failure is chained to the public FormulaParseError."""
    def fail_parser(*args: Any, **kwargs: Any) -> Any:
        """Simulate a SymPy parse failure independently of syntax validation."""
        raise ValueError("Parser failure")

    monkeypatch.setattr(engine, "parse_expr", fail_parser)
    with pytest.raises(FormulaParseError) as caught:
        calculate_indirect_measurement("1", {})
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize(
    "mean,error,expected",
    [(1.2345, 0.01234, (1.235, 0.012)), (1.2345, 0.02345, (1.235, 0.023)),
     (1.2345, 0.03456, (1.235, 0.035)), (1.2345, 0.04567, (1.23, 0.05)),
     (1.2345, 0.05678, (1.23, 0.06)), (1.2345, 0.06789, (1.23, 0.07)),
     (1.2345, 0.07891, (1.23, 0.08)), (1.2345, 0.08912, (1.23, 0.09)),
     (1.2345, 0.09123, (1.23, 0.09)), (1234, 123, (1230, 120)),
     (1234, 456, (1200, 500)), (1234, 99, (1200, 100)),
     (1.234, 0.099, (1.2, 0.1)), (12.345, 0.399, (12.35, 0.4)),
     (2.675, 0.045, (2.68, 0.05)), (-2.675, 0.045, (-2.68, 0.05)),
     (0.000123456, 0.000001234, (0.0001235, 0.0000012)),
     (1.23456789, 0, (1.23456789, 0)), (0, 0.015, (0, 0.015)),
     (1e-300, 5e-324, (1e-300, 5e-324))],
)
def test_rounding_rules(mean: float, error: float, expected: tuple[float, float]) -> None:
    """Check leading digits, carries, half ties, large/small scales and zero uncertainty."""
    assert round_measurement(mean, error) == expected


@pytest.mark.parametrize("mean,error", [(math.inf, 1), (1, math.nan), (1, -1), (True, 1), (1, "0.1")])
def test_invalid_rounding_input(mean: Any, error: Any) -> None:
    """Invalid rounding inputs use the same public validation exception."""
    with pytest.raises(InvalidInputError):
        round_measurement(mean, error)


def test_rounding_overflow_is_domain_error() -> None:
    """Rounding the largest finite value may leave the float domain."""
    with pytest.raises(MathDomainError):
        round_measurement(1, float.fromhex("0x1.fffffffffffffp+1023"))
