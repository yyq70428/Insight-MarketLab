"""Opt-in Discord notifier. All sends are guarded by PostgreSQL cooldown locks."""
import hashlib
import json
import threading
import requests
from ..config import get_settings
from ..analysis.engine import analyze
from .market_data import candles,frame_from_rows,quote,profile
from .store import watchlist_store
from .scanner import scanner


def alert_match(symbol,pattern,price,near_pct=0):
    low,high=pattern['prz']['low'],pattern['prz']['high']
    if not 0<low<=high or price<=0:return None
    distance=max(low-price,price-high,0)/price*100
    kind='trigger' if low<=price<=high else 'near' if near_pct>0 and distance<=near_pct else None
    if not kind:return None
    identity=[symbol,pattern['name'],pattern['direction'],pattern['status'],round(low,4),round(high,4),kind]
    return {'kind':kind,'distancePct':round(distance,4),'fingerprint':hashlib.sha256(json.dumps(identity).encode()).hexdigest()}


class AlertService:
    def __init__(self,store=watchlist_store,snapshot=scanner):
        self.store,self.scanner=store,snapshot;self.lock=threading.Lock();self.started=False;self.stop_event=threading.Event()

    def start(self):
        settings=get_settings()
        if not settings.alerts_enabled or not settings.discord_webhook_url:return
        with self.lock:
            if self.started:return
            self.started=True
        threading.Thread(target=self.loop,name='marketlab-alerts',daemon=True).start()

    def send_item(self,item,source):
        settings=get_settings()
        for pattern in item.get('patterns',[]):
            match=alert_match(item['symbol'],pattern,item['latestPrice'],settings.alert_near_pct)
            if not match:continue
            message=('進入 PRZ' if match['kind']=='trigger' else '接近 PRZ')+' · '+item['symbol']+' '+item.get('name','')
            description='\n'.join([f"來源：{source} · {item.get('market','')} · {item.get('industry','未知')}",
                f"{pattern['direction']} {pattern['name']} · {pattern['status']} · 評分 {pattern['score']}",
                f"現價 {item['latestPrice']} · PRZ {pattern['prz']['low']}–{pattern['prz']['high']}",
                f"距離 {match['distancePct']}% · 目標 {', '.join(map(str,pattern.get('targets',[])))}",
                '技術型態通知，不代表未來績效或投資建議。'])
            payload={'allowed_mentions':{'parse':[]},'embeds':[{'title':message[:256],'description':description[:3500],
                'color':0x18B7A6 if pattern['direction']=='bullish' else 0xFF525C}]}
            def deliver():
                try:
                    response=requests.post(settings.discord_webhook_url,json=payload,timeout=8)
                    return 200<=response.status_code<300
                except requests.RequestException:return False
            self.store.deliver_alert(match['fingerprint'],settings.alert_cooldown,deliver)

    def cycle(self):
        if not self.store.available():return
        checked=set()
        for watch in self.store.list():
            symbol=watch['symbol'];checked.add(symbol)
            try:
                data=analyze(frame_from_rows(candles(symbol,'1d','2y')['candles']));meta=profile(symbol);latest=quote(symbol)
                item={'symbol':symbol,'name':meta['name'],'market':'台股' if symbol.endswith(('.TW','.TWO')) else '加密資產' if symbol.endswith('-USD') else '美股',
                    'industry':meta.get('industry','未知'),'patterns':data['harmonics'],'latestPrice':latest['price']}
                self.send_item(item,'自選清單即時分析')
            except Exception:continue
        if get_settings().alert_universe:
            for item in self.scanner.get()['results']:
                if item['symbol'] not in checked:
                    try:self.send_item(item,'掃描器快照')
                    except Exception:continue

    def loop(self):
        while not self.stop_event.is_set():
            try:self.cycle()
            except Exception:pass
            self.stop_event.wait(max(30,get_settings().alert_interval))


alerts=AlertService()
