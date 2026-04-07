"""
Service-level tests with mocked internals.
==========================================
Tests async services (specs, market, vin_decoder) by mocking
their internal scraping functions, plus ADAC cost edge cases.
All tests are offline (no real network I/O).
Uses asyncio.run() like the existing test files.
"""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


def _run(coro):
    """Run a coroutine without disturbing the thread's current event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── 4a. specs_scraper ────────────────────────────────────────────────────────

from services.specs_scraper import (
    get_specs,
    _heuristic_key,
    _search_query,
    _extract_value,
    _parse_specs_html,
    _HEURISTIC,
)


def test_heuristic_key_lowercase():
    assert _heuristic_key("BMW", "3er") == "bmw|3er"


def test_heuristic_key_already_lower():
    assert _heuristic_key("volkswagen", "golf") == "volkswagen|golf"


def test_heuristic_key_preserves_pipe():
    key = _heuristic_key("Mercedes-Benz", "C-Klasse")
    assert "|" in key


def test_search_query_vw_alias():
    q = _search_query("vw", "Golf")
    assert "Volkswagen" in q or "Golf" in q


def test_search_query_basic():
    q = _search_query("BMW", "3er")
    assert "BMW" in q or "3er" in q


def test_extract_value_power_ps():
    val = _extract_value("power_ps", "156 PS")
    assert val == 156


def test_extract_value_power_hp():
    val = _extract_value("power_ps", "200 hp")
    assert val == 200


def test_extract_value_power_kw_conversion():
    val = _extract_value("power_ps", "100 kW")
    assert val == round(100 * 1.36)


def test_extract_value_fuel_consumption_comma():
    val = _extract_value("fuel_consumption", "5,6 l/100km")
    assert val == "5.6"


def test_extract_value_co2():
    val = _extract_value("co2", "148 g/km")
    assert val == "148 g/km"


def test_extract_value_dash_returns_none():
    val = _extract_value("top_speed", "–")
    assert val is None


def test_extract_value_unknown_field_passthrough():
    val = _extract_value("fuel_type", "Diesel")
    assert val == "Diesel"


def test_parse_specs_html_power():
    html = '<tr><td>Power</td><td>156 PS</td></tr>'
    data = _parse_specs_html(html)
    assert data.get("power_ps") == 156


def test_parse_specs_html_fuel_consumption():
    html = '<tr><td>Fuel consumption</td><td>5.6 l/100km</td></tr>'
    data = _parse_specs_html(html)
    assert "fuel_consumption" in data


def test_parse_specs_html_empty():
    data = _parse_specs_html("")
    assert data == {}


def test_parse_specs_html_no_matching_labels():
    html = '<tr><td>Color</td><td>Red</td></tr>'
    data = _parse_specs_html(html)
    assert data == {}


def test_get_specs_no_make_returns_empty():
    result = _run(get_specs({"vin": "X" * 17}))
    assert result == {}


def test_get_specs_heuristic_fallback_bmw():
    """When scraping returns empty, the heuristic table fills in BMW 3er."""
    with patch("services.specs_scraper._scrape_auto_data", new=AsyncMock(return_value={})):
        result = _run(get_specs({"make": "BMW", "model": "3er", "year": "2019"}))
    assert result.get("power_ps") == 156
    assert result.get("source") == "heuristic"


def test_get_specs_heuristic_fallback_unknown_model():
    """Unknown model → returns whatever _scrape_auto_data returns (empty)."""
    with patch("services.specs_scraper._scrape_auto_data", new=AsyncMock(return_value={})):
        result = _run(get_specs({"make": "Trabant", "model": "601", "year": "1985"}))
    assert isinstance(result, dict)


def test_get_specs_uses_scrape_result_when_has_power():
    from services.specs_scraper import _cache as _specs_cache
    _specs_cache.clear()
    scraped = {"power_ps": 200, "source": "auto-data.net"}
    with patch("services.specs_scraper._scrape_auto_data", new=AsyncMock(return_value=scraped)):
        result = _run(get_specs({"make": "BMW", "model": "3er", "year": "2019"}))
    assert result["power_ps"] == 200


def test_get_specs_scrape_exception_falls_back_to_heuristic():
    with patch("services.specs_scraper._scrape_auto_data", new=AsyncMock(side_effect=Exception("net"))):
        result = _run(get_specs({"make": "Volkswagen", "model": "Golf", "year": "2020"}))
    # Golf is in heuristic table
    assert "power_ps" in result


@pytest.mark.parametrize("make,model,key", [
    ("BMW",       "3er",    "bmw|3er"),
    ("Volkswagen","Golf",   "volkswagen|golf"),
    ("Volvo",     "V60",    "volvo|v60"),
])
def test_heuristic_table_coverage(make, model, key):
    assert key in _HEURISTIC, f"Heuristic table missing: {key}"


# ─── 4b. market_scraper ───────────────────────────────────────────────────────

from services.market_scraper import (
    scrape_market,
    get_market,
    _parse_price,
    _parse_km,
    _parse_year,
    _aggregate,
    _MAX_LISTINGS,
)


def test_parse_price_german_thousands():
    assert _parse_price("12.500 €") == 12_500


def test_parse_price_dash_suffix():
    assert _parse_price("9.990,-") == 9_990


def test_parse_price_eur_suffix():
    assert _parse_price("12.500 EUR") == 12_500


def test_parse_price_plain_integer():
    assert _parse_price("25000") == 25_000


def test_parse_price_too_low_returns_none():
    assert _parse_price("499") is None


def test_parse_price_too_high_returns_none():
    assert _parse_price("600000") is None


def test_parse_km_no_unit():
    assert _parse_km("80000") == "80000"


def test_parse_km_with_unit():
    assert _parse_km("80.000 km") == "80000"


def test_parse_km_with_us_format():
    assert _parse_km("80,000 km") == "80000"


def test_parse_year_found():
    assert _parse_year("EZ 2021") == "2021"


def test_parse_year_not_found():
    assert _parse_year("no year here") == ""


def test_aggregate_limits_to_max_listings():
    listings = [{"price": i * 1000, "title": str(i)} for i in range(1, 12)]
    result = _aggregate(listings)
    assert len(result["listings"]) <= _MAX_LISTINGS


def test_aggregate_empty_input():
    result = _aggregate([])
    assert result.get("avg_price") is None
    assert result.get("listings") == []


def test_aggregate_single_listing():
    listings = [{"price": 20_000, "title": "test"}]
    result = _aggregate(listings)
    assert result["avg_price"] == 20_000
    assert result["min_price"] == 20_000
    assert result["max_price"] == 20_000


def test_scrape_market_empty_make():
    result = _run(scrape_market("", ""))
    assert result == {}


def test_get_market_passes_context():
    ctx = {"make": "BMW", "model": "3er", "year": "2019"}
    with patch("services.market_scraper.scrape_market", new=AsyncMock(return_value={})) as mock:
        _run(get_market(ctx))
    mock.assert_awaited_once_with("BMW", "3er", "2019")


def test_scrape_market_uses_first_successful_source():
    """If mobile.de returns listings, autoscout24 is not called."""
    mobile_result = {"avg_price": 20_000, "listings": [{"title": "t", "price": 20_000}]}
    with (
        patch("services.market_scraper._mobile_de",   new=AsyncMock(return_value=mobile_result)),
        patch("services.market_scraper._autoscout24", new=AsyncMock(return_value={})) as as24,
    ):
        result = _run(scrape_market("BMW", "3er", "2019"))
    as24.assert_not_awaited()
    assert result["avg_price"] == 20_000


def test_scrape_market_falls_back_to_autoscout24():
    """If mobile.de returns nothing, autoscout24 is tried."""
    from services.market_scraper import _cache as _market_cache
    _market_cache.clear()
    as24_result = {"avg_price": 22_000, "listings": [{"title": "t", "price": 22_000}]}
    with (
        patch("services.market_scraper._mobile_de",   new=AsyncMock(return_value={})),
        patch("services.market_scraper._autoscout24", new=AsyncMock(return_value=as24_result)),
    ):
        result = _run(scrape_market("BMW", "3er", "2019"))
    assert result["avg_price"] == 22_000


def test_scrape_market_returns_empty_when_both_fail():
    from services.market_scraper import _cache as _market_cache
    _market_cache.clear()
    with (
        patch("services.market_scraper._mobile_de",   new=AsyncMock(return_value={})),
        patch("services.market_scraper._autoscout24", new=AsyncMock(return_value={})),
    ):
        result = _run(scrape_market("BMW", "3er", "2019"))
    assert result == {}


# ─── 4c. vin_decoder ──────────────────────────────────────────────────────────

from services.vin_decoder import (
    decode_vin,
    _wmi_decode,
    _clean,
    _year_from_char,
    _match_field,
)


def test_wmi_decode_bmw():
    result = _wmi_decode("WBA3A5G59DNP26082")
    assert result.get("make") == "BMW"


def test_wmi_decode_volvo():
    result = _wmi_decode("YV1ZWA8UDL2388160")
    assert result.get("make") == "Volvo"


def test_wmi_decode_unknown_prefix():
    result = _wmi_decode("ZZZ00000000000001")
    assert result.get("make") is None or result == {}


def test_wmi_decode_year_from_vin_pos9():
    # Position 9 = 'D' → 2013
    result = _wmi_decode("WBA3A5G59DNP26082")
    assert result.get("year") == "2013"


def test_clean_year_range_takes_first():
    d = {"make": "Volkswagen", "year": "2020-2023"}
    cleaned = _clean(d)
    assert cleaned["year"] == "2020"


def test_clean_year_noise_stripped():
    d = {"make": "VW", "year": "Golf (2019)"}
    cleaned = _clean(d)
    assert cleaned["year"] == "2019"


def test_clean_bmw_title():
    d = {"make": "bmw", "year": "2020"}
    cleaned = _clean(d)
    assert cleaned["make"] == "BMW"


def test_clean_mercedes_benz_preserved():
    d = {"make": "mercedes-benz", "year": "2020"}
    cleaned = _clean(d)
    assert "enz" in cleaned["make"].lower()


def test_year_from_char_A():
    assert _year_from_char("A") == 2010


def test_year_from_char_S():
    assert _year_from_char("S") == 2025


def test_year_from_char_digit_1():
    assert _year_from_char("1") == 2001


def test_year_from_char_invalid():
    assert _year_from_char("I") is None


def test_match_field_english_make():
    assert _match_field("Make") == "make"


def test_match_field_german_marke():
    assert _match_field("Marke") == "make"


def test_match_field_unknown():
    assert _match_field("Farbe") is None


def test_decode_vin_wmi_fallback():
    """When all online services fail, WMI decode is returned."""
    from services.vin_decoder import _cache as _vin_cache
    _vin_cache.clear()
    with (
        patch("services.vin_decoder._freevindecoder", new=AsyncMock(side_effect=Exception("net"))),
        patch("services.vin_decoder._driving_tests",  new=AsyncMock(side_effect=Exception("net"))),
        patch("services.vin_decoder._nhtsa",          new=AsyncMock(side_effect=Exception("net"))),
    ):
        result = _run(decode_vin("WBA3A5G59DNP26082"))
    assert result.get("make") == "BMW"
    assert result.get("source") == "WMI"


def test_decode_vin_nhtsa_success():
    nhtsa_data = {
        "make": "Bmw", "model": "3 Series", "year": "2013",
        "fuel_type": "Gasoline", "transmission": "Automatic",
    }
    with (
        patch("services.vin_decoder._freevindecoder", new=AsyncMock(side_effect=Exception("net"))),
        patch("services.vin_decoder._driving_tests",  new=AsyncMock(side_effect=Exception("net"))),
        patch("services.vin_decoder._nhtsa",          new=AsyncMock(return_value=nhtsa_data)),
    ):
        result = _run(decode_vin("WBA3A5G59DNP26082"))
    assert result.get("make") is not None
    assert result.get("confidence", 0) > 0


def test_decode_vin_freevindecoder_success():
    fvd_data = {"make": "BMW", "model": "3er", "year": "2013", "confidence": 0.90}
    with patch("services.vin_decoder._freevindecoder", new=AsyncMock(return_value=fvd_data)):
        result = _run(decode_vin("WBA3A5G59DNP26082X"))  # cache miss – unique VIN
    assert result.get("make") == "BMW"


def test_decode_vin_chain_falls_back_on_first_failure():
    """freevindecoder fails → driving-tests succeeds."""
    dt_data = {"make": "BMW", "model": "3er", "year": "2019"}
    with (
        patch("services.vin_decoder._freevindecoder", new=AsyncMock(side_effect=Exception("net"))),
        patch("services.vin_decoder._driving_tests",  new=AsyncMock(return_value=dt_data)),
    ):
        result = _run(decode_vin("WBA3A5G59DNP2608Z"))
    assert result.get("make") == "BMW"
    assert result.get("source") == "driving-tests.org"


# ─── 4d. ADAC cost edge cases ─────────────────────────────────────────────────

from services.adac_parser import (
    _heuristic,
    estimate_monthly_costs,
    get_costs,
    _COST_TABLE,
)


def test_heuristic_dacia_economy():
    result = _heuristic("Dacia", "Sandero", "2020")
    assert result["fuel_monthly"] == _COST_TABLE["economy"]["fuel_monthly"]
    assert result["source"] == "heuristic (ADAC-based estimate)"


def test_heuristic_unknown_brand_midrange():
    result = _heuristic("Unbekannt", "X200", "2020")
    assert result["fuel_monthly"] == _COST_TABLE["mid"]["fuel_monthly"]


def test_heuristic_future_year_no_adjustment():
    """A future year (age ≤ 5) should NOT trigger the old-car adjustment."""
    result_new = _heuristic("BMW", "3er", "2024")
    result_old = _heuristic("BMW", "3er", "2010")
    # Old car: maintenance is higher, depreciation lower
    assert result_old["maintenance_monthly"] > result_new["maintenance_monthly"]
    assert result_old["depreciation_monthly"] < result_new["depreciation_monthly"]


def test_heuristic_very_old_car_adjustment():
    """Cars older than 5 years get depreciation * 0.6, maintenance * 1.3."""
    base_depr = _COST_TABLE["mid"]["depreciation_monthly"]
    base_maint = _COST_TABLE["mid"]["maintenance_monthly"]
    result = _heuristic("Volkswagen", "Golf", "2015")  # age > 5
    assert result["depreciation_monthly"] == round(base_depr * 0.6)
    assert result["maintenance_monthly"]  == round(base_maint * 1.3)


def test_estimate_costs_total_equals_sum_of_components():
    result = estimate_monthly_costs("BMW", "3er", "2020")
    components = (
        result["fuel_monthly"]
        + result["insurance_monthly"]
        + result["tax_monthly"]
        + result["maintenance_monthly"]
        + result["depreciation_monthly"]
    )
    assert result["total_monthly"] == round(components)


def test_estimate_costs_all_components_positive():
    result = estimate_monthly_costs("Volkswagen", "Golf", "2021")
    for key in ("fuel_monthly", "insurance_monthly", "tax_monthly",
                "maintenance_monthly", "depreciation_monthly"):
        assert result[key] > 0, f"{key} should be > 0"


def test_estimate_costs_source_contains_heuristic():
    result = estimate_monthly_costs("Toyota", "Corolla", "2019")
    assert "heuristic" in result.get("source", "")


def test_get_costs_returns_dict(bmw_ctx):
    result = get_costs(bmw_ctx)
    assert isinstance(result, dict)
    assert "total_monthly" in result


def test_get_costs_sparse_ctx(sparse_ctx):
    result = get_costs(sparse_ctx)
    assert isinstance(result, dict)


def test_costs_luxury_higher_than_economy():
    bmw  = estimate_monthly_costs("BMW", "5er", "2022")
    dacia = estimate_monthly_costs("Dacia", "Duster", "2022")
    assert bmw["total_monthly"] > dacia["total_monthly"]


def test_costs_older_car_higher_maintenance():
    new_car = estimate_monthly_costs("Volkswagen", "Golf", "2022")
    old_car = estimate_monthly_costs("Volkswagen", "Golf", "2010")
    assert old_car["maintenance_monthly"] > new_car["maintenance_monthly"]
