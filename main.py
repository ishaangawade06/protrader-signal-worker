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
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")  # kept if needed later

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

# --- Data fetcher using yfinance ---
def symbol_to_yf(symbol, market):
    s = symbol.strip()
    if market == 'crypto':
        if s.endswith('USDT'):
            return s[:-4] + '-USD'   # BTCUSDT -> BTC-USD
        if s.endswith('USD'):
            return s[:-3] + '-USD'
        return s
    if market == 'forex':
        if s.endswith('=X'):
            return s
        return s + '=X'
    return s

def fetch_yahoo_data(symbol, market, interval='1m', limit=200):
    yf_symbol = symbol_to_yf(symbol, market)
    period = "1d"
    if interval.endswith('d') or interval == '1d':
        period = "7d"
    try:
        df = yf.download(tickers=yf_symbol, period=period, interval=interval, progress=False)
    except Exception as e:
        raise RuntimeError(f"yfinance download error for {yf_symbol}: {e}")

    if df is None or df.empty:
        raise RuntimeError(f"No data returned from yfinance for {yf_symbol} interval={interval}")

    # ✅ Fix: Flatten MultiIndex if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join([str(c) for c in col if c]) for col in df.columns.values]

    # Rename columns to lowercase
    df = df.rename(columns={c: str(c).lower() for c in df.columns})

    # Ensure required columns exist
    for col in ['open','high','low','close','volume']:
        if col not in df.columns:
            raise RuntimeError(f"Missing expected column {col} in {yf_symbol}")

    df = df.tail(limit)

    # Ensure numeric types
    for c in ['open','high','low','close','volume']:
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

# push to Firestore
def push_signal_to_firestore(doc):
    global db
    col = db.collection('signals')
    col.add(doc)
    print(f"Pushed signal: {doc.get('symbol')} {doc.get('signal')}")

# send FCM topic notification
def send_fcm(title, body, data=None, topic=None):
    try:
        if topic is None:
            topic = FCM_TOPIC
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
    symbol = cfg['symbol']
    market = cfg.get('market','crypto')
    interval = cfg.get('interval','1m')
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
                "notes": "To compute position size for a user: risk_amount = user_balance * (risk_percent/100). "
                         "units = risk_amount / abs(entry - stop_loss). Then position_value = units * entry_price. "
                         "Mobile app should compute this using the user's connected broker balance."
            }
        }
        push_signal_to_firestore(doc)

        if sig['signal'] in ('BUY','SELL'):
            title = f"ProTraderHack {sig['signal']} {symbol}"
            body = f"{sig['signal']} {symbol} @ {last_price:.4f} - {', '.join(sig.get('reasons',[]))}"
            send_fcm(title, body, data={"symbol": symbol, "signal": sig['signal']}, topic=FCM_TOPIC)
            topic_safe = ("signals_" + symbol.replace(".", "_").replace("/", "_")).lower()
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
    print("Loaded symbols:", symbols)
    for cfg in symbols:
        print("Processing:", cfg['symbol'], type(cfg['symbol']))
        process_symbol(cfg)

if __name__ == "__main__":
    main()
