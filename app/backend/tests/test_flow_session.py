from datetime import date
import pytest
from fastapi import HTTPException
from app.backend.validators import normalize_symbol, parse_anchor, validate_interval


def test_symbol_normalization_for_taiwan_us_and_crypto():
    assert normalize_symbol("2330") == "2330.TW"
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol("btc-usd") == "BTC-USD"


def test_invalid_symbols_and_flow_intervals_are_rejected():
    with pytest.raises(HTTPException): normalize_symbol("AAPL<script>")
    with pytest.raises(HTTPException): validate_interval("1wk", flow=True)


def test_anchor_requires_iso_date():
    assert parse_anchor("2026-07-02") == date(2026, 7, 2)
    with pytest.raises(HTTPException): parse_anchor("07/02/2026")
