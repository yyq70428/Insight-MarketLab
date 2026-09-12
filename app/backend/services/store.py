from __future__ import annotations

from datetime import datetime, timezone, timedelta
try:
    import psycopg
except ImportError:  # Optional locally; installed by the production requirements.
    psycopg = None
from ..config import get_settings


class WatchlistStore:
    def __init__(self):
        self.url = get_settings().database_url

    def available(self):
        if not self.url or psycopg is None:
            return False
        try:
            with psycopg.connect(self.url, connect_timeout=3) as connection:
                connection.execute("SELECT 1")
            return True
        except Exception:
            return False

    def initialize(self):
        if not self.url or psycopg is None:
            return
        with psycopg.connect(self.url) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol VARCHAR(24) PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS alert_log (fingerprint TEXT PRIMARY KEY, sent_at TIMESTAMPTZ NOT NULL)")

    def list(self):
        with psycopg.connect(self.url) as connection:
            return [{"symbol": row[0], "createdAt": row[1].isoformat()} for row in connection.execute("SELECT symbol, created_at FROM watchlist ORDER BY created_at")]

    def add(self, symbol: str):
        with psycopg.connect(self.url) as connection:
            connection.execute("INSERT INTO watchlist(symbol, created_at) VALUES (%s, %s) ON CONFLICT DO NOTHING", (symbol, datetime.now(timezone.utc)))

    def remove(self, symbol: str):
        with psycopg.connect(self.url) as connection:
            connection.execute("DELETE FROM watchlist WHERE symbol=%s", (symbol,))

    def deliver_alert(self,fingerprint,cooldown,deliver):
        with psycopg.connect(self.url,connect_timeout=3) as connection:
            # Transaction advisory lock prevents concurrent workers sending twice.
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(fingerprint,))
            previous=connection.execute('SELECT sent_at FROM alert_log WHERE fingerprint=%s',(fingerprint,)).fetchone()
            current=datetime.now(timezone.utc)
            if previous and previous[0]>current-timedelta(seconds=cooldown):return False
            if not deliver():return False
            connection.execute('INSERT INTO alert_log(fingerprint,sent_at) VALUES(%s,%s) ON CONFLICT(fingerprint) DO UPDATE SET sent_at=EXCLUDED.sent_at',(fingerprint,current))
            return True


watchlist_store = WatchlistStore()
