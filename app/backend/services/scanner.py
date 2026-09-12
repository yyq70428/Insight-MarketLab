from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import ROOT, get_settings
from ..analysis.engine import analyze
from .market_data import candles, frame_from_rows, profile


class Scanner:
    def __init__(self):
        self.lock = threading.Lock()
        self.snapshot = {"scanning": False, "total": 0, "completed": 0, "results": [], "startedAt": None, "updatedAt": None}
        self.started = False

    def get(self):
        with self.lock:
            return dict(self.snapshot)

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self._loop, name="marketlab-scanner", daemon=True).start()

    def _symbols(self):
        config=get_settings()
        path = Path(config.scan_symbols_file) if config.scan_symbols_file else ROOT / "app/backend/data/scan_symbols.txt"
        rows = []
        lines=config.scan_symbols.replace(',','\n').splitlines() if config.scan_symbols else path.read_text(encoding='utf-8').splitlines() if path.exists() else ['0050.TW|ETF','AAPL|科技','BTC-USD|加密資產']
        from ..validators import normalize_symbol
        for line in lines:
            if line.strip() and not line.startswith("#"):
                symbol, _, industry = line.partition("|")
                try:rows.append((normalize_symbol(symbol.strip()),industry.strip() or '未知'))
                except Exception:continue
        return list(dict.fromkeys(rows))

    def _loop(self):
        config = get_settings()
        while True:
            symbols = self._symbols()
            with self.lock:
                self.snapshot.update(scanning=True, total=len(symbols), completed=0, startedAt=datetime.now(timezone.utc).isoformat())
            for symbol, industry in symbols:
                try:
                    payload = candles(symbol, config.scan_candle_interval, "2y")
                    result = analyze(frame_from_rows(payload["candles"]), config.max_harmonic_results, config.max_sr_zones)
                    try:
                        meta = profile(symbol)
                    except Exception:
                        meta = {"name": symbol, "currency": ""}
                    market = "台股" if symbol.endswith((".TW", ".TWO")) else "加密資產" if symbol.endswith("-USD") else "美股"
                    item = {"symbol": symbol, "name": meta.get("name", symbol), "market": market, "industry": industry if industry!='未知' else meta.get('industry','未知'),
                            "currency": meta.get("currency", ""), "interval": config.scan_candle_interval,
                            "latestPrice": result["latestPrice"], "patterns": result["harmonics"], "scannedAt": datetime.now(timezone.utc).isoformat()}
                    with self.lock:
                        previous = [row for row in self.snapshot["results"] if row["symbol"] != symbol]
                        self.snapshot["results"] = sorted(previous + [item],key=lambda row:max(((p['status']=='completed',p['score'],p['points'][-1]['time']) for p in row['patterns']),default=(False,0,0)),reverse=True)
                except Exception:
                    pass
                with self.lock:
                    self.snapshot["completed"] += 1
                time.sleep(max(0, config.scan_fetch_delay))
            with self.lock:
                self.snapshot.update(scanning=False, updatedAt=datetime.now(timezone.utc).isoformat())
            time.sleep(max(30, config.scan_interval))


scanner = Scanner()
