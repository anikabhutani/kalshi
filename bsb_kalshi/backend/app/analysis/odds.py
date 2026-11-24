"""Odds conversions for the sportsbook overlay (M7).

Formulas:
- American odds A >= +100: implied probability = 100 / (A + 100).
- American odds A <= -100: implied probability = -A / (-A + 100).
  Values strictly between -100 and +100 are not valid American odds.
- Decimal odds D > 1: implied probability = 1 / D.
- No-vig (two-way, proportional): p_i / (p_a + p_b) for each outcome; the overround is
  p_a + p_b - 1.
- Kalshi: a YES contract pays $1.00, so a YES price in dollars divided by 1.00 is its implied
  probability. Fees are not included.
"""

from __future__ import annotations

PAYOUT_DOLLARS = 1.0


def american_to_probability(odds: float) -> float:
    """Implied probability of American odds."""
    if -100 < odds < 100:
        raise ValueError(f"{odds:g} is not valid American odds (must be <= -100 or >= +100)")
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def decimal_to_probability(odds: float) -> float:
    """Implied probability of decimal odds."""
    if odds <= 1.0:
        raise ValueError(f"{odds:g} is not valid decimal odds (must be > 1)")
    return 1.0 / odds


def american_to_decimal(odds: float) -> float:
    """Decimal odds equivalent to American odds."""
    if -100 < odds < 100:
        raise ValueError(f"{odds:g} is not valid American odds (must be <= -100 or >= +100)")
    return 1.0 + odds / 100.0 if odds > 0 else 1.0 + 100.0 / -odds


def probability_to_american(probability: float) -> float:
    """American odds whose implied probability is ``probability`` (0 < p < 1)."""
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    if probability >= 0.5:
        return -100.0 * probability / (1.0 - probability)
    return 100.0 * (1.0 - probability) / probability


def no_vig_two_way(p_a: float, p_b: float) -> tuple[float, float]:
    """Proportionally normalized probabilities of a two-outcome market."""
    total = p_a + p_b
    if total <= 0:
        raise ValueError("implied probabilities must sum to a positive number")
    return p_a / total, p_b / total


def overround(p_a: float, p_b: float) -> float:
    """Sum of the two implied probabilities minus one."""
    return p_a + p_b - 1.0


def kalshi_price_to_probability(price_dollars: float) -> float:
    """Implied probability of a YES price in dollars (contract pays $1.00)."""
    if not 0.0 <= price_dollars <= PAYOUT_DOLLARS:
        raise ValueError(f"{price_dollars:g} is outside the $0.00-$1.00 YES price range")
    return price_dollars / PAYOUT_DOLLARS
