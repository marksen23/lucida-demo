"""Tests for market_scraper – _parse_price, _parse_km, _aggregate (unit tests, no network)."""

import pytest
from services.market_scraper import _parse_price, _parse_km, _parse_year, _aggregate


# ─── _parse_price ─────────────────────────────────────────────────────────────

def test_parse_price_german_format():
    assert _parse_price("12.500 €") == 12_500

def test_parse_price_german_large():
    assert _parse_price("33.900 €") == 33_900

def test_parse_price_plain_int():
    assert _parse_price("27500") == 27_500

def test_parse_price_with_eur():
    assert _parse_price("15.990 EUR") == 15_990

def test_parse_price_vk_format():
    assert _parse_price("9.990,-") == 9_990

def test_parse_price_none_too_low():
    assert _parse_price("100") is None  # below 500 threshold

def test_parse_price_none_too_high():
    assert _parse_price("1000000") is None  # above 500k threshold

def test_parse_price_empty():
    assert _parse_price("") is None

def test_parse_price_text_only():
    assert _parse_price("Preis auf Anfrage") is None

def test_parse_price_nbsp_format():
    # Non-breaking space as thousands separator
    assert _parse_price("24\xa0900\xa0€") == 24_900

def test_parse_price_six_digit():
    assert _parse_price("123456") == 123_456


# ─── _parse_km ────────────────────────────────────────────────────────────────

def test_parse_km_with_unit():
    assert _parse_km("150.000 km") == "150000"

def test_parse_km_with_unit_comma():
    assert _parse_km("150,000 km") == "150000"

def test_parse_km_no_unit_plain():
    assert _parse_km("85000") == "85000"

def test_parse_km_no_unit_short():
    assert _parse_km("5000") == "5000"

def test_parse_km_concatenated():
    assert _parse_km("120000km") == "120000"

def test_parse_km_empty():
    assert _parse_km("") == ""

def test_parse_km_text_only():
    assert _parse_km("keine Angabe") == ""

def test_parse_km_plain_int_object():
    # JSON integer comes as string "85000"
    assert _parse_km("85000") == "85000"


# ─── _parse_year ──────────────────────────────────────────────────────────────

def test_parse_year_found():
    assert _parse_year("BMW 3er 2019") == "2019"

def test_parse_year_four_digit():
    assert _parse_year("2021") == "2021"

def test_parse_year_not_found():
    assert _parse_year("keine Angabe", fallback="2020") == "2020"

def test_parse_year_future_not_matched():
    # Future year 2035 → not matched (pattern caps at 202x)
    result = _parse_year("Model 2035")
    assert result == "" or result != "2035"  # regex only accepts 19xx/200x/201x/202x


# ─── _aggregate ───────────────────────────────────────────────────────────────

def test_aggregate_single_listing():
    listings = [{"price": 25_000, "mileage": "80000", "title": "BMW 320d", "year": "2019", "source": "test", "url": None}]
    result = _aggregate(listings)
    assert result["avg_price"] == 25_000
    assert result["min_price"] == 25_000
    assert result["max_price"] == 25_000

def test_aggregate_multiple_listings():
    listings = [
        {"price": 20_000, "mileage": "50000", "title": "A", "year": "2019", "source": "test", "url": None},
        {"price": 25_000, "mileage": "80000", "title": "B", "year": "2020", "source": "test", "url": None},
        {"price": 30_000, "mileage": "90000", "title": "C", "year": "2021", "source": "test", "url": None},
    ]
    result = _aggregate(listings)
    assert result["avg_price"] == 25_000
    assert result["min_price"] == 20_000
    assert result["max_price"] == 30_000

def test_aggregate_no_prices():
    listings = [{"price": None, "mileage": "", "title": "X", "year": "", "source": "test", "url": None}]
    result = _aggregate(listings)
    assert "avg_price" not in result  # no price data → no avg

def test_aggregate_empty():
    result = _aggregate([])
    assert result == {"listings": []}

def test_aggregate_limits_to_max_listings():
    """_aggregate should cap at _MAX_LISTINGS (3) in the output."""
    listings = [
        {"price": 10_000 + i * 1_000, "mileage": "50000", "title": f"Car {i}",
         "year": "2020", "source": "test", "url": None}
        for i in range(10)
    ]
    result = _aggregate(listings)
    assert len(result["listings"]) <= 3
