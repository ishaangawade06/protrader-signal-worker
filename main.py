# main.py
import os, json, time, traceback
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
from dateutil import parser

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# CONFIG
FIREBASE_SECRET_ENV = "FIREBASE_SERVICE_ACCOUNT"
FCM_TOPIC = os.environ.get("FCM_TOPIC", "signals")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")
BINANCE_BASE = "https://api.binance.com/api/v3/klines"

# Helper: initialize Firebase from secret JSON string
def init_firebase_from_env():
    raw = os.environ.get(FIREBASE_SECRET_ENV)
    if not raw:
        raise RuntimeError(f"Environment var {FIREBASE_SECRET_ENV} not found")
    try:
        service_account_info = json.loads(raw)
    except Exception:
        # maybe it's base64-encoded; try decode
        import base64
        service_account_info = json.loads(base64.b64decode(raw).decode())
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)
    return firestore.client()

db = None

# Fetch klines from Binance (public)
def fetch_binance_klines(symbol, interval='1m', limit=200):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(BINANCE_BASE, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    # kline: [openTime, open, high, low, close, volume, ...]
    df = pd.DataFrame(data, columns=["open_time","open","high","low","close","volume",
                                     "close_time","qav","num_trades","taker_base","taker_quote","ignore"])
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df.set_index('open_time')
    return df

# Fetch intraday from Alpha Vantage
def fetch_alpha_intraday(symbol, interval='5min', outputsize='compact'):
    if not ALPHA_VANTAGE_KEY:
        raise RuntimeError("Alpha Vantage key not set")
    url = "https://www.alphavantage.co/query"
    params = {"function":"TIME_SERIES_INTRADAY", "symbol":symbol, "interval":interval,
              "outputsize":outputsize, "apikey":ALPHA_VANTAGE_KEY, "datatype":"json"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    # find time series key
    ts_key = next((k for k in payload.keys() if "Time Series" in k), None)
    if not ts_key:
        raise RuntimeError("AlphaVantage error: " + json.dumps(payload))
    ts = payload[ts_key]
    df = pd.DataFrame.from_dict(ts, orient='index')
    df = df.rename(columns=lambda s: s.split('. ')[1] if '. ' in s else s)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.astype(float)
    df = df.rename(columns={"open":"open","high":"high","low":"low","close":"close","volume":"volume"})
    return df

# Indicators
def add_indicators(df):
    close = df['close']
    df['sma_fast'] = close.rolling(window=9, min_periods=1).mean()
    df['sma_slow'] = close.rolling(window=21, min_periods=1).mean()
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1*delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs.fillna(0)))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    return df

def compute_signal(df):
    if len(df) < 5:
        return {'signal':'HOLD', 'reasons':['insufficient data']}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    reasons = []
    cross_up = (prev['sma_fast'] <= prev['sma_slow']) and (last['sma_fast'] > last['sma_slow'])
    cross_down = (prev['sma_fast'] >= prev['sma_slow']) and (last['sma_fast'] < last['sma_slow'])
    macd_cross_up = (prev['macd'] <= prev['macd_signal']) and (last['macd'] > last['macd_signal'])
    macd_cross_down = (prev['macd'] >= prev['macd_signal']) and (last['macd'] < last['macd_signal'])
    rsi = float(last.get('rsi', 50))
    if cross_up and macd_cross_up and rsi < 75:
        return {'signal':'BUY', 'reasons':['SMA cross up','MACD confirm', f'RSI={rsi:.1f}']}
    if cross_down and macd_cross_down and rsi > 25:
        return {'signal':'SELL', 'reasons':['SMA cross down','MACD confirm', f'RSI={rsi:.1f}']}
    return {'signal':'HOLD', 'reasons':['No strong confirmation'], 'rsi':rsi}

# Simple support/resistance: return last 3 local minima/maxima from closes
def compute_support_resistance(df, lookback=50):
    closes = df['close'].iloc[-lookback:]
    highs = closes.rolling(window=5, center=True).apply(lambda x: 1 if x[2]==x.max() else 0, raw=True)
    lows = closes.rolling(window=5, center=True).apply(lambda x: 1 if x[2]==x.min() else 0, raw=True)
    supports = list(closes[lows==1].round(2).unique())[-3:]
    resistances = list(closes[highs==1].round(2).unique())[-3:]
    # fallback to simple min/max
    if not supports:
        supports = [round(float(closes.min()),2)]
    if not resistances:
        resistances = [round(float(closes.max()),2)]
    return supports, resistances

# push to Firestore
def push_signal_to_firestore(doc):
    global db
    col = db.collection('signals')
    col.add(doc)
    print(f"Pushed signal: {doc.get('symbol')} {doc.get('signal')}")

# send FCM topic notification
def send_fcm(title, body, data=None):
    try:
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic=FCM_TOPIC,
            data=data or {}
        )
        resp = messaging.send(msg)
        print("FCM sent:", resp)
    except Exception as e:
        print("FCM error:", e)

# process one symbol config
def process_symbol(cfg):
    symbol = cfg['symbol']
    market = cfg.get('market','crypto')
    interval = cfg.get('interval','1m')
    try:
        if market == 'crypto':
            df = fetch_binance_klines(symbol, interval=interval, limit=200)
        elif market in ('indian','forex'):
            df = fetch_alpha_intraday(symbol, interval=interval, outputsize='compact')
        else:
            raise RuntimeError("Unknown market "+market)
        df = add_indicators(df)
        sig = compute_signal(df)
        supports, resistances = compute_support_resistance(df, lookback=min(120, len(df)))
        last_price = float(df['close'].iloc[-1])
        # build document
        doc = {
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "signal": sig['signal'],
            "reasons": sig.get('reasons', []),
            "indicators": {
                "sma_fast": float(df['sma_fast'].iloc[-1]),
                "sma_slow": float(df['sma_slow'].iloc[-1]),
                "macd": float(df['macd'].iloc[-1]),
                "macd_signal": float(df['macd_signal'].iloc[-1]),
                "rsi": float(df['rsi'].iloc[-1])
            },
            "entry": float(df['close'].iloc[-1]),  # using last price as entry suggestion (adjustable)
            "stop_loss": round(float(df['close'].iloc[-1]) * 0.99, 4),  # example 1% stop
            "take_profits": [ round(float(df['close'].iloc[-1]) * 1.02,4) ],
            "support_levels": supports,
            "resistance_levels": resistances,
            "last_price": last_price,
            "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        }
        push_signal_to_firestore(doc)
        # send notification if BUY or SELL
        if sig['signal'] in ('BUY','SELL'):
            title = f"ProTraderHack {sig['signal']} {symbol}"
            body = f"{sig['signal']} {symbol} @ {last_price:.4f} - {', '.join(sig.get('reasons',[]))}"
            send_fcm(title, body, data={"symbol":symbol,"signal":sig['signal']})
    except Exception as e:
        print("Error processing", symbol, str(e))
        traceback.print_exc()

def load_symbols():
    with open('symbols.json','r') as f:
        return json.load(f).get('symbols', [])

def main():
    global db
    db = init_firebase_from_env()
    symbols = load_symbols()
    print("Loaded symbols:", symbols)
    for cfg in symbols:
        process_symbol(cfg)

if __name__ == "__main__":
    main()
