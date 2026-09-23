"""The fixed daily-report universe: 60 Taiwan names plus 10 US large caps.

This is a hand-maintained snapshot, NOT a live index feed. The Taiwan large-cap block
overlaps the FTSE TWSE Taiwan 50 index heavily but membership is rebalanced quarterly,
so treat the list as a watchlist that needs a periodic human review rather than as an
authoritative copy of 0050. Listing venue matters: .TW is TWSE, .TWO is TPEX, and a
wrong suffix simply fails to resolve upstream — `verify_universe()` exists to catch that.

US picks are deliberately limited to mega caps. The news Agent sources 鉅亨網, whose
US coverage (`wd_stock`) concentrates on the largest names; thinner tickers would
report insufficient evidence almost every day and add cost for nothing.
"""
from __future__ import annotations

# (symbol, display name, bucket)
TAIWAN_LARGE_CAP: tuple[tuple[str, str, str], ...] = (
    ("2330.TW", "台積電", "半導體"),
    ("2317.TW", "鴻海", "電子組裝"),
    ("2454.TW", "聯發科", "半導體"),
    ("2308.TW", "台達電", "電子零組件"),
    ("2382.TW", "廣達", "電子組裝"),
    ("2881.TW", "富邦金", "金融"),
    ("2891.TW", "中信金", "金融"),
    ("2882.TW", "國泰金", "金融"),
    ("2303.TW", "聯電", "半導體"),
    ("3711.TW", "日月光投控", "半導體封測"),
    ("2412.TW", "中華電", "電信"),
    ("1216.TW", "統一", "食品"),
    ("2886.TW", "兆豐金", "金融"),
    ("2884.TW", "玉山金", "金融"),
    ("2357.TW", "華碩", "電腦週邊"),
    ("3034.TW", "聯詠", "半導體"),
    ("2892.TW", "第一金", "金融"),
    ("5880.TW", "合庫金", "金融"),
    ("2885.TW", "元大金", "金融"),
    ("2890.TW", "永豐金", "金融"),
    ("2887.TW", "台新金", "金融"),
    ("1303.TW", "南亞", "塑化"),
    ("1301.TW", "台塑", "塑化"),
    ("2002.TW", "中鋼", "鋼鐵"),
    ("3008.TW", "大立光", "光學"),
    ("2207.TW", "和泰車", "汽車"),
    ("2379.TW", "瑞昱", "半導體"),
    ("3037.TW", "欣興", "PCB"),
    ("2301.TW", "光寶科", "電子零組件"),
    ("2603.TW", "長榮", "航運"),
    ("1326.TW", "台化", "塑化"),
    ("2880.TW", "華南金", "金融"),
    ("2883.TW", "開發金", "金融"),
    ("2609.TW", "陽明", "航運"),
    ("2615.TW", "萬海", "航運"),
    ("4938.TW", "和碩", "電子組裝"),
    ("6505.TW", "台塑化", "塑化"),
    ("2327.TW", "國巨", "被動元件"),
    ("3045.TW", "台灣大", "電信"),
    ("4904.TW", "遠傳", "電信"),
    ("5871.TW", "中租-KY", "租賃"),
    ("1101.TW", "台泥", "水泥"),
    ("1102.TW", "亞泥", "水泥"),
    ("2912.TW", "統一超", "零售"),
    ("9904.TW", "寶成", "紡織製鞋"),
    ("6415.TW", "矽力-KY", "半導體"),
    ("3661.TW", "世芯-KY", "IC 設計"),
    ("6669.TW", "緯穎", "伺服器"),
    ("3231.TW", "緯創", "電子組裝"),
    ("2345.TW", "智邦", "網通"),
)

# Smaller names with a clearer single-theme story; higher beta, thinner news coverage.
TAIWAN_POTENTIAL: tuple[tuple[str, str, str], ...] = (
    ("2408.TW", "南亞科", "記憶體"),
    ("8046.TW", "南電", "PCB"),
    ("6446.TW", "藥華藥", "生技"),
    ("1590.TW", "亞德客-KY", "工業自動化"),
    ("3529.TWO", "力旺", "IP 矽智財"),
    ("6488.TWO", "環球晶", "半導體矽晶圓"),
    ("4966.TWO", "譜瑞-KY", "IC 設計"),
    ("3443.TW", "創意", "IC 設計"),
    ("8299.TWO", "群聯", "記憶體控制"),
    ("3653.TW", "健策", "散熱"),
)

US_LARGE_CAP: tuple[tuple[str, str, str], ...] = (
    ("AAPL", "Apple", "消費電子"),
    ("MSFT", "Microsoft", "軟體雲端"),
    ("NVDA", "NVIDIA", "半導體"),
    ("GOOGL", "Alphabet", "網路平台"),
    ("AMZN", "Amazon", "電商雲端"),
    ("META", "Meta Platforms", "網路平台"),
    ("TSLA", "Tesla", "電動車"),
    ("AMD", "AMD", "半導體"),
    ("AVGO", "Broadcom", "半導體"),
    ("NFLX", "Netflix", "串流媒體"),
)

UNIVERSE: tuple[tuple[str, str, str], ...] = TAIWAN_LARGE_CAP + TAIWAN_POTENTIAL + US_LARGE_CAP

SYMBOLS: tuple[str, ...] = tuple(symbol for symbol, _, _ in UNIVERSE)
NAMES: dict[str, str] = {symbol: name for symbol, name, _ in UNIVERSE}
SECTORS: dict[str, str] = {symbol: sector for symbol, _, sector in UNIVERSE}


def market_of(symbol: str) -> str:
    return "台股" if symbol.endswith((".TW", ".TWO")) else "美股"


def verify_universe(loader) -> list[dict]:
    """Resolve every symbol through `loader` and report the ones that fail.

    A wrong listing suffix is silent until the scheduler runs, so this is meant to be
    called from a test or an ops check rather than at import time.
    """
    broken = []
    for symbol, name, _ in UNIVERSE:
        try:
            rows = loader(symbol)
            if not rows:
                broken.append({"symbol": symbol, "name": name, "error": "沒有回傳任何 K 線"})
        except Exception as exc:  # upstream failures are the point of the check
            broken.append({"symbol": symbol, "name": name, "error": str(exc)})
    return broken
