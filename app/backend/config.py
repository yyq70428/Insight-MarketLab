from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "*"
    quote_cache_ttl: int = 5
    intraday_cache_ttl: int = 15
    daily_cache_ttl: int = 60
    search_cache_ttl: int = 300
    metadata_cache_ttl: int = 3600
    profile_cache_ttl: int = 86400
    news_cache_ttl: int = 300
    cache_max_items: int = 256
    max_harmonic_results: int = 8
    max_sr_zones: int = 6
    upstream_timeout: float = 6
    upstream_user_agent: str = "Mozilla/5.0 MarketLab/1.0"
    news_max_pages_per_round: int = 10
    news_max_articles: int = 8
    news_timeout: float = 8
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.6-luna"
    openai_timeout: float = 90
    agent_report_ttl: int = 3600
    mongodb_uri: str = ""
    mongodb_database: str = "marketlab"
    database_url: str = ""
    ragas_enabled: bool = False
    ragas_api_key: str = ""
    ragas_model: str = ""
    ragas_base_url: str = ""
    ragas_timeout: float = 120
    scan_interval: int = 900
    scan_symbols: str = ""
    scan_symbols_file: str = ""
    scan_candle_interval: str = "1d"
    scan_fetch_delay: float = 0.4
    discord_webhook_url: str = ""
    alerts_enabled: bool = False
    alert_interval: int = 300
    alert_cooldown: int = 86400
    alert_universe: bool = True
    alert_near_pct: float = 0
    flow_max_rounds: int = 20
    # Absolute origin used for links inside the mailed report; a relative href would
    # resolve against the mail client. Empty means the report ships without links.
    public_base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_timeout: float = 20
    report_recipients: str = ""
    daily_report_enabled: bool = False
    daily_report_time: str = "18:00"
    daily_report_timezone: str = "Asia/Taipei"
    # A restart after the scheduled time must not trigger a surprise full run; the job only
    # fires inside this window, so short downtime is tolerated but yesterday's slot is not.
    daily_report_window_minutes: int = 120
    daily_report_weekdays_only: bool = True
    daily_report_delay: float = 1.5
    daily_report_candle_period: str = "2y"
    yahoo_search_url: str = "https://query2.finance.yahoo.com/v1/finance/search"
    anue_news_url: str = "https://news.cnyes.com/api/v3/news/category"
    anue_archive_url: str = "https://news.cnyes.com/news/cat"
    twse_directory_url: str = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    tpex_directory_url: str = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
    twse_codequery_url: str = "https://www.twse.com.tw/rwd/zh/api/codeQuery"
    finmind_token: str = ""

    @property
    def cors_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def recipient_list(self) -> list[str]:
        return [item.strip() for item in self.report_recipients.replace(";", ",").split(",") if item.strip()]

    @property
    def sender_address(self) -> str:
        return self.smtp_from or self.smtp_user


@lru_cache
def get_settings() -> Settings:
    file_values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                file_values[key.strip().lower()] = value.strip().strip('"').strip("'")
    merged = {**file_values, **{key.lower(): value for key, value in os.environ.items()}}
    aliases = {
        "cache_ttl_quote": "quote_cache_ttl",
        "cache_ttl_intraday": "intraday_cache_ttl",
        "cache_ttl_daily": "daily_cache_ttl",
        "cache_ttl_search": "search_cache_ttl",
        "cache_ttl_meta": "metadata_cache_ttl",
        "cache_ttl_profile": "profile_cache_ttl",
        "cache_ttl_news": "news_cache_ttl",
        "cache_max_entries": "cache_max_items",
    }
    for source, target in aliases.items():
        if source in merged and target not in merged:
            merged[target] = merged[source]
    fields = Settings.model_fields
    parsed = {}
    for name, field in fields.items():
        if name not in merged:
            continue
        value = merged[name]
        try:
            if field.annotation is bool:
                parsed[name] = value.lower() in {"1", "true", "yes", "on"}
            elif field.annotation is int:
                parsed[name] = int(value)
            elif field.annotation is float:
                parsed[name] = float(value)
            else:
                parsed[name] = value
        except (TypeError, ValueError):
            pass
    return Settings(**parsed)
