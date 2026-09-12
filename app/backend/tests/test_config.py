from app.backend import config


def test_documented_cache_aliases_are_supported(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_QUOTE", "17")
    monkeypatch.setenv("CACHE_MAX_ENTRIES", "91")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.quote_cache_ttl == 17
    assert settings.cache_max_items == 91
    config.get_settings.cache_clear()
