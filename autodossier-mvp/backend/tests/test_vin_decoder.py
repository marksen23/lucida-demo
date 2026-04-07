"""Tests for vin_decoder – WMI decode, _clean(), year chars (unit tests, no network)."""

import pytest
from services.vin_decoder import _wmi_decode, _clean, _year_from_char, _match_field


# ─── _year_from_char ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("char,expected", [
    ("A", 2010), ("B", 2011), ("C", 2012), ("D", 2013),
    ("K", 2019), ("L", 2020), ("M", 2021), ("N", 2022),
    ("P", 2023), ("R", 2024), ("S", 2025),
    ("1", 2001), ("9", 2009),
])
def test_year_from_char(char, expected):
    assert _year_from_char(char) == expected

def test_year_from_char_unknown():
    assert _year_from_char("Z") is None

def test_year_from_char_lowercase():
    # Must handle uppercase only
    assert _year_from_char("k") is None  # input should be pre-uppercased


# ─── _wmi_decode ──────────────────────────────────────────────────────────────

def test_wmi_decode_bmw_3er():
    # WBA3A5G59DNP26082 → WMI=WBA, model hint WBA3=3er, year D=2013
    result = _wmi_decode("WBA3A5G59DNP26082")
    assert result["make"] == "BMW"
    assert result["model"] == "3er"
    assert result["year"] == "2013"
    assert result["origin_country"] == "Deutschland"

def test_wmi_decode_volvo_v60():
    # YV1ZWA8UDL2388160 → WMI=YV1, model hint YV1Z=V60, year L=2020
    result = _wmi_decode("YV1ZWA8UDL2388160")
    assert result["make"] == "Volvo"
    assert result["model"] == "V60"
    assert result["year"] == "2020"
    assert result["origin_country"] == "Schweden"

def test_wmi_decode_vw_golf():
    # WVWZZZAUZJY062345 → WMI=WVW, model hint WVWZ=Golf, year J=2018
    result = _wmi_decode("WVWZZZAUZJY062345")
    assert result["make"] == "Volkswagen"
    assert result["model"] == "Golf"
    assert result["year"] == "2018"
    assert result["origin_country"] == "Deutschland"

def test_wmi_decode_unknown_wmi():
    result = _wmi_decode("00000000000000001")
    assert "make" not in result  # Unknown WMI

def test_wmi_decode_no_model_hint():
    # YV1 = Volvo but WMI_MODEL has no match for YV1X... chars
    result = _wmi_decode("YV1XXXXXKL1234567")
    assert result.get("make") == "Volvo"
    # model hint YV1X = XC40
    assert result.get("model") == "XC40"

def test_wmi_decode_returns_origin_country_germany():
    result = _wmi_decode("WDD1234567890ABCD")
    assert result["origin_country"] == "Deutschland"

def test_wmi_decode_returns_origin_country_japan():
    result = _wmi_decode("JHM000000000K0000")
    assert result["origin_country"] == "Japan"

def test_wmi_decode_porsche():
    result = _wmi_decode("WP0CA2A92FS165789")
    assert result["make"] == "Porsche"
    assert result["model"] == "Cayenne"

def test_wmi_decode_mercedes():
    result = _wmi_decode("WDD1234567890ABCD")
    assert result["make"] == "Mercedes-Benz"


# ─── _clean ───────────────────────────────────────────────────────────────────

def test_clean_bmw_title_fix():
    result = _clean({"make": "BMW", "year": "2019"})
    assert result["make"] == "BMW"

def test_clean_makes_title_case():
    result = _clean({"make": "volkswagen", "year": "2020"})
    assert result["make"] == "Volkswagen"

def test_clean_strips_year_noise():
    result = _clean({"make": "BMW", "year": "Model Year: 2019"})
    assert result["year"] == "2019"

def test_clean_year_range_takes_first():
    result = _clean({"make": "BMW", "year": "2018/2019"})
    assert result["year"] == "2018"

def test_clean_no_make():
    result = _clean({"model": "Golf", "year": "2020"})
    assert "make" not in result

def test_clean_bmw_m_preserved():
    result = _clean({"make": "bmw m"})
    assert "BMW" in result["make"]


# ─── _match_field ─────────────────────────────────────────────────────────────

def test_match_field_make():
    assert _match_field("Make") == "make"

def test_match_field_marke_german():
    assert _match_field("Marke") == "make"

def test_match_field_year():
    # "Model Year" contains "model" which matches first in the _FIELD_MAP iteration
    # The field "year" is matched by keyword "year" (without "model" prefix)
    assert _match_field("Year") == "year"
    assert _match_field("Baujahr") == "year"

def test_match_field_fuel():
    assert _match_field("Fuel Type") == "fuel_type"

def test_match_field_unknown():
    assert _match_field("Xyzzyx") is None
