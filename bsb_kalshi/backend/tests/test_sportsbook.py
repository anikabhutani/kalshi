"""Sportsbook CSV parsing, two-way no-vig grouping, dummy data and the overlay (M7)."""

from __future__ import annotations

import pytest

from app.analysis.sportsbook import (
    DUMMY_LABEL,
    TEMPLATE_COLUMNS,
    TEMPLATE_CSV,
    CsvError,
    KalshiSeries,
    dummy_csv,
    overlay,
    parse_csv,
)
from app.analysis.timeseries import PricePoint

HEADER = ",".join(TEMPLATE_COLUMNS)


def test_template_parses_with_no_vig() -> None:
    parsed = parse_csv(TEMPLATE_CSV)
    assert parsed.error_count == 0 and len(parsed.rows) == 4
    first = parsed.rows[:2]
    assert first[0]["implied_prob"] == pytest.approx(120 / 220)
    assert first[1]["implied_prob"] == pytest.approx(0.5)
    assert first[0]["no_vig_prob"] + first[1]["no_vig_prob"] == pytest.approx(1.0)
    assert first[0]["overround"] == pytest.approx(120 / 220 + 0.5 - 1)
    assert parsed.rows[2]["odds_format"] == "decimal"
    assert parsed.rows[2]["implied_prob"] == pytest.approx(1 / 1.8)
    assert all("DUMMY" in r["book"] for r in parsed.rows)


def test_row_errors_are_reported_and_skipped() -> None:
    text = "\n".join(
        [
            HEADER,
            "2026-01-01T00:00:00Z,Book,Ev,Yes,-150,",
            "not a time,Book,Ev,Yes,-150,",
            "2026-01-01T00:00:00Z,Book,Ev,No,50,",
            "2026-01-01T00:00:00Z,,Ev,No,+130,",
            "2026-01-01T00:00:00Z,Book,Ev,No,,",
            "2026-01-01T00:00:00Z,Book,Ev,No,+130,1.5",
            "2026-01-01T00:00:00Z,Book,Ev,No,nan,",
            "2026-01-01T00:00:00Z,Book,Ev,No,,1.0",
        ]
    )
    parsed = parse_csv(text)
    assert len(parsed.rows) == 1
    assert parsed.error_count == 7
    assert [e["line"] for e in parsed.errors] == [3, 4, 5, 6, 7, 8, 9]
    assert "disagrees" in parsed.errors[4]["message"]
    assert parsed.rows[0]["no_vig_prob"] is None
    assert "exactly two outcomes" in parsed.rows[0]["group_note"]


def test_matching_american_and_decimal_are_accepted() -> None:
    parsed = parse_csv(f"{HEADER}\n2026-01-01T00:00:00Z,B,E,Yes,+150,2.50\n")
    assert parsed.rows[0]["odds_format"] == "american" and parsed.rows[0]["implied_prob"] == pytest.approx(0.4)


def test_naive_timestamps_are_utc_and_noted() -> None:
    parsed = parse_csv(f"{HEADER}\n2026-01-01T00:00:00,B,E,Yes,+100,\n2026-01-01T00:00:00Z,B,E,No,+100,\n")
    assert parsed.rows[0]["ts"] == parsed.rows[1]["ts"]
    assert parsed.naive_timestamps == 1 and parsed.notes
    assert parsed.rows[0]["no_vig_prob"] == pytest.approx(0.5)


def test_duplicate_outcome_rows_get_no_no_vig() -> None:
    parsed = parse_csv(f"{HEADER}\n2026-01-01T00:00:00Z,B,E,Yes,+100,\n2026-01-01T00:00:00Z,B,E,Yes,+110,\n")
    assert all(r["no_vig_prob"] is None for r in parsed.rows)
    assert parsed.rows[0]["group_note"].startswith("duplicate")


def test_file_level_errors() -> None:
    with pytest.raises(CsvError, match="Missing column"):
        parse_csv("timestamp_utc,book\n")
    with pytest.raises(CsvError, match="odds_american or odds_decimal"):
        parse_csv("timestamp_utc,book,event,market\n2026-01-01T00:00:00Z,B,E,M\n")
    with pytest.raises(CsvError, match="No valid rows"):
        parse_csv(f"{HEADER}\nbad,B,E,M,+100,\n")
    with pytest.raises(CsvError, match="no data rows"):
        parse_csv(f"{HEADER}\n")


def test_non_numeric_odds_name_the_column() -> None:
    with pytest.raises(CsvError, match="odds_american 'abc' is not a number"):
        parse_csv(f"{HEADER}\n2026-01-01T00:00:00Z,B,E,M,abc,\n")
    with pytest.raises(CsvError, match="odds_decimal '1,5' is not a number"):
        parse_csv(f'{HEADER}\n2026-01-01T00:00:00Z,B,E,M,,"1,5"\n')


def test_decimal_only_file() -> None:
    parsed = parse_csv("timestamp_utc,book,event,market,odds_decimal\n2026-01-01T00:00:00Z,B,E,Yes,1.5\n2026-01-01T00:00:00Z,B,E,No,2.6\n")
    assert parsed.rows[0]["no_vig_prob"] == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 2.6))


def test_dummy_data_is_labelled_deterministic_and_parses() -> None:
    text = dummy_csv(1_700_000_000, 1_700_003_600, "MKT-1", seed=7)
    assert text == dummy_csv(1_700_000_000, 1_700_003_600, "MKT-1", seed=7)
    parsed = parse_csv(text)
    assert parsed.error_count == 0
    assert len({r["ts"] for r in parsed.rows}) == 13
    assert all(DUMMY_LABEL in r["event"] and "DUMMY" in r["book"] and "dummy" in r["market"] for r in parsed.rows)
    assert all(r["no_vig_prob"] is not None and r["overround"] > 0 for r in parsed.rows)


def test_dummy_data_point_count_is_bounded() -> None:
    parsed = parse_csv(dummy_csv(0, 30 * 86_400, "X", seed=1))
    assert len({r["ts"] for r in parsed.rows}) <= 1001


def test_overlay_gaps_use_price_at_and_staleness() -> None:
    rows = parse_csv(
        "\n".join(
            [
                HEADER,
                "2026-01-01T00:10:00Z,B,E,Yes,-150,",
                "2026-01-01T00:10:00Z,B,E,No,+130,",
                "2026-01-01T02:00:00Z,B,E,Yes,+100,",
                "2026-01-01T02:00:00Z,B,E,No,-120,",
                "2025-12-31T23:00:00Z,B,E,Yes,+100,",
            ]
        )
    ).rows
    base = 1_767_225_600
    series = KalshiSeries("trades:price", "trades", "", [PricePoint(base + 300, 0.55), PricePoint(base + 900, 0.65)])
    out = overlay(rows, "Yes", series, max_staleness_s=600)
    early, fresh, stale = out["rows"]
    assert early["kalshi_price"] is None and early["gap_no_vig_pp"] is None
    assert fresh["kalshi_price"] == 0.55 and fresh["staleness_s"] == 300
    novig_yes = 0.6 / (0.6 + 100 / 230)
    assert fresh["gap_no_vig_pp"] == pytest.approx((0.55 - novig_yes) * 100)
    assert fresh["gap_implied_pp"] == pytest.approx((0.55 - 0.6) * 100)
    assert stale["kalshi_price"] == 0.65 and not stale["within_staleness"] and stale["gap_no_vig_pp"] is None
    (summary,) = out["summary"]
    assert summary["rows"] == 3 and summary["with_kalshi_price"] == 2 and summary["within_staleness"] == 1
    assert summary["mean_abs_gap_no_vig_pp"] == pytest.approx(abs((0.55 - novig_yes) * 100))
