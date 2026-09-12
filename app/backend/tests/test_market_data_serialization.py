import json
import numpy as np
import pandas as pd
import pytest

from app.backend.services import market_data


class FakeTicker:
    fast_info = {"currency": "TWD"}

    def history(self, **_kwargs):
        return pd.DataFrame(
            {
                "Open": [np.nan, 100.0, 101.0],
                "High": [np.nan, 102.0, 103.0],
                "Low": [np.nan, 99.0, 100.0],
                "Close": [np.nan, 101.0, 102.0],
                "Volume": [np.nan, np.nan, 1000.0],
            },
            index=pd.date_range("2026-01-01", periods=3, tz="UTC"),
        )


def test_quote_drops_invalid_ohlc_and_never_returns_nan(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda _symbol: FakeTicker())
    market_data.cache.data.clear()
    result = market_data.quote("0050.TW")
    assert result["price"] == 102.0
    assert result["volume"] == 1000
    assert "NaN" not in json.dumps(result, allow_nan=False)


def test_non_finite_optional_number_is_none():
    assert market_data._finite_number(float("nan")) is None
    assert market_data._finite_number(float("inf")) is None


def test_download_validation_sorts_deduplicates_and_rejects_bad_ohlc():
    frame = pd.DataFrame({
        "Date": pd.to_datetime(["2026-01-02", "2026-01-01", "2026-01-02", "2026-01-03"]),
        "Open": [10, 9, 11, 12], "High": [11, 10, 12, 11], "Low": [9, 8, 10, 10],
        "Close": [10.5, 9.5, 11.5, 12.5], "Volume": [100, 90, 110, 120],
    }).set_index("Date")
    cleaned, time_col = market_data._clean_download(frame)
    assert time_col == "Date"
    assert len(cleaned) == 2
    assert cleaned.iloc[0]["Date"] < cleaned.iloc[1]["Date"]
    assert cleaned.iloc[-1]["Open"] == 11


def ticker_frame(symbol):
    frame = FakeTicker().history().iloc[1:].copy()
    frame.index.name = 'Date'
    frame.columns = pd.MultiIndex.from_product([frame.columns, [symbol]], names=['Price', 'Ticker'])
    return frame


def test_download_rejects_another_ticker_before_removing_multiindex():
    with pytest.raises(LookupError, match='標的與請求不一致'):
        market_data._clean_download(ticker_frame('AAPL'), '2330.TW')
    clean, _ = market_data._clean_download(ticker_frame('2330.TW'), '2330.TW')
    assert len(clean) == 2


def test_download_rejects_accidentally_combined_tickers():
    mixed = pd.concat([ticker_frame('2330.TW'), ticker_frame('AAPL')], axis=1)
    with pytest.raises(LookupError, match='標的與請求不一致'):
        market_data._clean_download(mixed, '2330.TW')


def test_parallel_scanner_and_chart_downloads_are_serialized(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    state = {'active': 0, 'peak': 0}
    lock = threading.Lock()
    def download(symbol, **kwargs):
        assert kwargs['threads'] is False
        with lock:
            state['active'] += 1
            state['peak'] = max(state['peak'], state['active'])
        time.sleep(.02)
        result = ticker_frame(symbol)
        with lock: state['active'] -= 1
        return result
    monkeypatch.setattr(market_data.yf, 'download', download)
    monkeypatch.setattr(market_data, 'cache', market_data.TTLCache())
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda symbol:market_data.candles(symbol,'1d','2y'), ['2330.TW','AAPL','0050.TW','MSFT']))
    assert state['peak'] == 1
    assert [r['symbol'] for r in rows] == ['2330.TW','AAPL','0050.TW','MSFT']


def test_wrong_ticker_is_never_cached(monkeypatch):
    monkeypatch.setattr(market_data, 'cache', market_data.TTLCache())
    monkeypatch.setattr(market_data.yf, 'download', lambda *a, **kw:ticker_frame('AAPL'))
    with pytest.raises(LookupError, match='標的與請求不一致'):
        market_data.candles('2330.TW','1d','2y')
    assert market_data.cache.data == {}
