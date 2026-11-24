"""Odds conversion math (M7)."""

from __future__ import annotations

import pytest

from app.analysis.odds import (
    american_to_decimal,
    american_to_probability,
    decimal_to_probability,
    kalshi_price_to_probability,
    no_vig_two_way,
    overround,
    probability_to_american,
)


@pytest.mark.parametrize(
    ("american", "probability"),
    [(100, 0.5), (-100, 0.5), (150, 0.4), (-150, 0.6), (300, 0.25), (-400, 0.8), (-110, 110 / 210)],
)
def test_american_to_probability(american: float, probability: float) -> None:
    assert american_to_probability(american) == pytest.approx(probability)


@pytest.mark.parametrize("bad", [0, 50, -50, 99.9, -99.9])
def test_american_between_minus_and_plus_100_is_invalid(bad: float) -> None:
    with pytest.raises(ValueError):
        american_to_probability(bad)
    with pytest.raises(ValueError):
        american_to_decimal(bad)


@pytest.mark.parametrize(("decimal", "probability"), [(2.0, 0.5), (1.25, 0.8), (4.0, 0.25), (1.909, 1 / 1.909)])
def test_decimal_to_probability(decimal: float, probability: float) -> None:
    assert decimal_to_probability(decimal) == pytest.approx(probability)


@pytest.mark.parametrize("bad", [1.0, 0.5, 0, -2])
def test_decimal_must_exceed_one(bad: float) -> None:
    with pytest.raises(ValueError):
        decimal_to_probability(bad)


@pytest.mark.parametrize(("american", "decimal"), [(100, 2.0), (150, 2.5), (-200, 1.5), (-110, 1 + 100 / 110)])
def test_american_to_decimal_agrees_with_probabilities(american: float, decimal: float) -> None:
    assert american_to_decimal(american) == pytest.approx(decimal)
    assert decimal_to_probability(american_to_decimal(american)) == pytest.approx(american_to_probability(american))


@pytest.mark.parametrize("p", [0.1, 0.25, 0.5, 0.6, 0.8, 0.95])
def test_probability_to_american_round_trips(p: float) -> None:
    assert american_to_probability(probability_to_american(p)) == pytest.approx(p)


def test_probability_to_american_rejects_bounds() -> None:
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            probability_to_american(bad)


def test_no_vig_standard_minus_110_market() -> None:
    p = american_to_probability(-110)
    a, b = no_vig_two_way(p, p)
    assert a == pytest.approx(0.5) and b == pytest.approx(0.5)
    assert overround(p, p) == pytest.approx(2 * 110 / 210 - 1)


def test_no_vig_lopsided_market_sums_to_one() -> None:
    fav, dog = american_to_probability(-200), american_to_probability(170)
    a, b = no_vig_two_way(fav, dog)
    assert a + b == pytest.approx(1.0)
    assert a == pytest.approx(fav / (fav + dog))
    assert overround(fav, dog) == pytest.approx(fav + dog - 1)
    with pytest.raises(ValueError):
        no_vig_two_way(0, 0)


def test_kalshi_price_to_probability() -> None:
    assert kalshi_price_to_probability(0.0) == 0.0
    assert kalshi_price_to_probability(0.57) == pytest.approx(0.57)
    assert kalshi_price_to_probability(1.0) == 1.0
    for bad in (-0.01, 1.01, 57):
        with pytest.raises(ValueError):
            kalshi_price_to_probability(bad)
