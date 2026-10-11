"""Physical conversions, uncertainty propagation and dimension rejection."""

import math

import pytest

from calc_engine import (
    MeasurementValue, calculate_direct_measurement,
    calculate_indirect_measurement, calculate_unequal_measurements,
)
from units_engine import InvalidUnitError, Quantity, format_dimension, parse_unit


@pytest.mark.parametrize("unit, value", [
    ("мм", 1e-3), ("см", 1e-2), ("км", 1e3), ("мкм", 1e-6), ("нм", 1e-9),
    ("г", 1e-3), ("мг", 1e-6), ("кг", 1), ("мс", 1e-3), ("МПа", 1e6),
    ("mm", 1e-3), ("μm", 1e-6), ("kg", 1), ("g/cm^3", 1e3),
    ("мм/мс", 1), ("кг*(м/с)**2", 1),
])
def test_input_scales(unit, value):
    assert Quantity(1, unit).to_si() == pytest.approx(value)


@pytest.mark.parametrize("unit", ["bananas", "°C", "м+с", "м**x", "м/0", "__import__('os')", "м**10000", "м**1e999", "True"])
def test_invalid_units(unit):
    with pytest.raises(InvalidUnitError):
        parse_unit(unit)


def test_direct_conversion_scales_observations_and_all_errors():
    result = calculate_direct_measurement([25.3, 25.5], 0.1, unit="мм")
    reference = calculate_direct_measurement([0.0253, 0.0255], 0.0001, unit="м")
    assert result.mean == pytest.approx(reference.mean)
    assert result.total_error == pytest.approx(reference.total_error)
    assert result.instr_error == pytest.approx(0.0001)
    assert result.raw_data == pytest.approx(reference.raw_data)
    assert result.table_rows[0]["diff_sq"] == pytest.approx(1e-8)
    assert result.unit == "м"


def test_energy_and_uncertainty_are_si_and_can_be_reused():
    result = calculate_indirect_measurement("m*v**2/2", {
        "m": MeasurementValue(500, 5, "г"), "v": MeasurementValue(200, 2, "см/с"),
    })
    assert result.value == pytest.approx(1)
    assert result.total_error == pytest.approx(math.hypot(0.01, 0.02))
    assert result.unit == "Дж"
    reused = calculate_indirect_measurement("Ekin*2", {
        "Ekin": MeasurementValue(result.value, result.total_error, result.unit),
    }, derived_units=False)
    assert reused.value == pytest.approx(2)
    assert reused.unit == "м²·кг/с²"


@pytest.mark.parametrize("formula", ["x+t", "x-t", "(x+t)-(x+t)", "sin(x)", "log(x)", "x**t", "x**p"])
def test_dimension_errors_are_not_hidden_by_simplification(formula):
    with pytest.raises(InvalidUnitError):
        calculate_indirect_measurement(formula, {
            "x": MeasurementValue(2, 0.1, "м"),
            "t": MeasurementValue(1, 0.1, "с"),
            "p": MeasurementValue(2, 0.1),
        })


def test_fractional_dimensions_and_expected_result_validation():
    result = calculate_indirect_measurement("sqrt(area)", {"area": MeasurementValue(4, 0.2, "м²")})
    assert result.value == 2
    assert result.unit == "м"
    with pytest.raises(InvalidUnitError):
        calculate_indirect_measurement("area", {"area": MeasurementValue(4, 0.2, "м²")}, unit="с")


def test_unequal_series_convert_before_weighting():
    result = calculate_unequal_measurements([
        MeasurementValue(1000, 10, "мм"), MeasurementValue(102, 2, "см"),
    ])
    assert result.mean == pytest.approx(1.004)
    assert result.total_error == pytest.approx(1 / math.sqrt(12500))
    assert result.contributions == pytest.approx([0.8, 0.2])
    assert result.unit == "м"
    with pytest.raises(InvalidUnitError):
        calculate_unequal_measurements([MeasurementValue(1, 0.1, "м"), MeasurementValue(1, 0.1, "с")])


@pytest.mark.parametrize("unit", ["м", "кг", "с", "А", "К", "моль", "кд", "Н", "Па", "Дж", "В", "Па·с", "м/с²", "м^(1/2)"])
@pytest.mark.parametrize("derived", [True, False])
def test_formatted_si_units_round_trip(unit, derived):
    dimension = parse_unit(unit).dimension
    canonical = parse_unit(format_dimension(dimension, derived))
    assert canonical.dimension == dimension
    assert canonical.multiplier == 1
