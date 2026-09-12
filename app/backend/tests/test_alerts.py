from datetime import datetime,timezone
from unittest.mock import Mock
from app.backend.services.alerts import alert_match,AlertService
from app.backend.services.store import WatchlistStore
from app.backend.services import store as store_module
from app.backend.services import alerts as alerts_module


def pattern():return {'name':'Gartley','direction':'bullish','status':'completed','score':90,'prz':{'low':99,'high':101},'targets':[105]}


def test_trigger_and_near_fingerprints_are_distinct_and_stable():
    hit=alert_match('0050.TW',pattern(),100,2)
    near=alert_match('0050.TW',pattern(),98,2)
    assert hit['kind']=='trigger' and near['kind']=='near'
    assert hit['fingerprint']!=near['fingerprint']
    assert hit['fingerprint']==alert_match('0050.TW',pattern(),100.5,2)['fingerprint']
    assert alert_match('0050.TW',pattern(),90,2) is None


def test_postgres_cooldown_and_failed_delivery_are_not_recorded(monkeypatch):
    connection=Mock();manager=Mock();manager.__enter__=Mock(return_value=connection);manager.__exit__=Mock(return_value=False)
    monkeypatch.setattr(store_module.psycopg,'connect',Mock(return_value=manager))
    store=WatchlistStore();callback=Mock(return_value=True)
    connection.execute.return_value.fetchone.return_value=(datetime.now(timezone.utc),)
    assert not store.deliver_alert('test',3600,callback);callback.assert_not_called()
    connection.execute.return_value.fetchone.return_value=None;callback.return_value=False;connection.reset_mock()
    assert not store.deliver_alert('test',3600,callback)
    assert not any('INSERT' in str(call) for call in connection.execute.call_args_list)
    callback.return_value=True;connection.reset_mock()
    assert store.deliver_alert('test',3600,callback)
    assert any('INSERT' in str(call) for call in connection.execute.call_args_list)


def test_disabled_alerts_do_not_start_thread_or_send(monkeypatch):
    monkeypatch.setattr(alerts_module,'get_settings',lambda:Mock(alerts_enabled=False,discord_webhook_url='not-used'))
    service=AlertService();service.start();assert not service.started
