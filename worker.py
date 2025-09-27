# worker.py
import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
from signals import hybrid_signal

BACKEND_URL = os.getenv("BACKEND_URL", "https://protrader-backend-sbus.onrender.com")

def fetch_data(symbol="BTC-USD", interval="5m", limit=120):
    """Fetch OHLCV data from Yahoo Finance"""
    df = yf.download(tickers=symbol, period="1d", interval=interval)
    df = df.tail(limit)
    df = df.reset_index()
    df.rename(columns={
        "Date": "time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    }, inplace=True)
    return df

def run_signal(symbol="BTC-USD"):
    df = fetch_data(symbol)
    if df.empty:
        print("⚠️ No data for", symbol)
        return

    sig = hybrid_signal(df)
    payload = {
        "symbol": symbol,
        "signal": sig["signal"],
        "confidence": sig["confidence"],
        "reasons": sig["reasons"],
        "last_price": sig["meta"]["last_price"],
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        res = requests.post(f"{BACKEND_URL}/add-signal", json=payload)
        if res.status_code == 200:
            print(f"✅ Signal pushed: {symbol} {sig['signal']} @ {sig['meta']['last_price']}")
        else:
            print("❌ Error pushing signal:", res.text)
    except Exception as e:
        print("🔥 Failed to push signal:", e)

if __name__ == "__main__":
    # You can expand to multiple symbols/timeframes later
    run_signal("BTC-USD")
