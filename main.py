# main.py
import os, json, time, traceback
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
from dateutil import parser

# yfinance
import yfinance as yf

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# CONFIG
FIREBASE_SECRET_ENV = "FIREBASE_SERVICE_ACCOUNT"
FCM_TOPIC = os.environ.get("FCM_TOPIC", "signals")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

# Helper: initialize Firebase from secret JSON string
def init_firebase_from_env():
    raw = os.environ.get(FIREBASE_SECRET_ENV)
    if not raw:
        raise RuntimeError(f"Environment var {FIREBASE_SECRET_ENV} not found")
    try:
        service_account_info = json.loads(raw)
    except Exception:
        import base64
        service_account_info = json.loads(base64.b64decode(raw).decode())
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)
    return firestore.client()

db = None

# --- Data fetcher using yfinance ---
def symbol_to_yf(symbol, market):
    """Map symbols to yfinance format."""
    s = str(symbol).strip()
    if market == 'crypto':
        if s.endswith('USDT'):
            return s[:-4] + '-USD'
        if s.endswith('USD'):
            return s[:-3] + '-USD'
        return s
    if market == 'forex':
        if not s.endswith('=X'):
            return s + '=X'
        return s
    return s

def fetch_yahoo_data(symbol, market, interval='1m', limit=200):
    yf_symbol = symbol_to_yf(symbol, market)
    period = "1d"
    if interval.endswith('d') or interval == '1d':
        period = "7d"
    try:
        df = yf.download(tickers=yf_symbol, period=period, interval=interval, progress=False)
    except Exception as e:
        raise RuntimeError(f"yfinance error for {yf_symbol}: {e}")
    if df is None or df.empty:
        raise RuntimeError(f"No data returned for {yf_symbol}")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if 'close' not in df.columns:
        raise RuntimeError(f"No close column for {yf_symbol}")
    df = df.tail(limit)
    for c in ['open','high','low','close','volume']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['close'])
    df.index.name = 'open_time'
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
    last, prev = df.iloc[-1], df.iloc[-2]
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

def compute_support_resistance(df, lookback=50):
    closes = df['close'].iloc[-lookback:]
    if len(closes) < 5:
        return [round(float(closes.min()),2)], [round(float(closes.max()),2)]
    highs = closes.rolling(window=5, center=True).apply(lambda x: 1 if x[2]==x.max() else 0, raw=True)
    lows = closes.rolling(window=5, center=True).apply(lambda x: 1 if x[2]==x.min() else 0, raw=True)
    supports = list(closes[lows==1].round(4).unique())[-3:]
    resistances = list(closes[highs==1].round(4).unique())[-3:]
    if not supports:
        supports = [round(float(closes.min()),4)]
    if not resistances:
        resistances = [round(float(closes.max()),4)]
    return supports, resistances

def push_signal_to_firestore(doc):
    global db
    db.collection('signals').add(doc)
    print(f"Pushed: {doc.get('symbol')} {doc.get('signal')}")

def send_fcm(title, body, data=None, topic=None):
    try:
        topic = topic or FCM_TOPIC
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic=topic,
            data=data or {}
        )
        resp = messaging.send(msg)
        print("FCM sent:", resp)
    except Exception as e:
        print("FCM error:", e)

def process_symbol(cfg):
    symbol = str(cfg.get('symbol', '')).strip()
    market = str(cfg.get('market', 'crypto')).lower()
    interval = str(cfg.get('interval', '1m')).lower()
    print("Processing:", symbol, type(symbol))
    try:
        df = fetch_yahoo_data(symbol, market, interval=interval, limit=200)
        df = add_indicators(df)
        sig = compute_signal(df)
        supports, resistances = compute_support_resistance(df, lookback=min(120, len(df)))
        last_price = float(df['close'].iloc[-1])
        entry_price = last_price
        stop_loss = round(last_price * 0.99, 8)
        take_profit = round(last_price * 1.02, 8)
        risk_percent = float(cfg.get('risk_percent', 2.0))

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
            "entry": entry_price,
            "stop_loss": stop_loss,
            "take_profits": [take_profit],
            "support_levels": supports,
            "resistance_levels": resistances,
            "last_price": last_price,
            "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "risk_meta": {
                "risk_percent": risk_percent,
                "notes": "App should calculate position size based on user balance and risk."
            }
        }
        push_signal_to_firestore(doc)
        if sig['signal'] in ('BUY','SELL'):
            title = f"ProTraderHack {sig['signal']} {symbol}"
            body = f"{sig['signal']} {symbol} @ {last_price:.4f}"
            send_fcm(title, body, data={"symbol": symbol, "signal": sig['signal']}, topic=FCM_TOPIC)
            topic_safe = ("signals_" + symbol.replace(".", "_")).lower()
            send_fcm(title, body, data={"symbol": symbol, "signal": sig['signal']}, topic=topic_safe)

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
    print("Loaded:", symbols)
    for cfg in symbols:
        process_symbol(cfg)

if __name__ == "__main__":
    main()
