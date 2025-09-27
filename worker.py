# worker.py
import os
import requests
import yfinance as yf
from datetime import datetime
from signals import hybrid_signal

BACKEND_URL = os.getenv("BACKEND_URL", "https://protrader-backend-sbus.onrender.com")

# Define assets and timeframes
SYMBOLS = [
    "BTC-USD", "ETH-USD",   # Crypto
    "AAPL", "TSLA", "MSFT", # Stocks
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", # Forex
    "^NSEI"  # Nifty 50
]
TIMEFRAMES = ["5m", "15m", "1h", "1d"]

def fetch_data(symbol, interval="5m", limit=120):
    try:
        df = yf.download(tickers=symbol, period="5d", interval=interval)
        df = df.tail(limit).reset_index()
        df.rename(columns={
            "Date": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        }, inplace=True)
        return df
    except Exception as e:
        print(f"⚠️ Failed to fetch {symbol} {interval}: {e}")
        return None

def run_signal(symbol, interval):
    df = fetch_data(symbol, interval)
    if df is None or df.empty:
        return

    sig = hybrid_signal(df)
    payload = {
        "symbol": symbol,
        "interval": interval,
        "signal": sig["signal"],
        "confidence": sig["confidence"],
        "reasons": sig["reasons"],
        "last_price": sig["meta"]["last_price"],
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        res = requests.post(f"{BACKEND_URL}/add-signal", json=payload)
        if res.status_code == 200:
            print(f"✅ {symbol} [{interval}] → {sig['signal']} @ {sig['meta']['last_price']}")
        else:
            print("❌ Error pushing signal:", res.text)
    except Exception as e:
        print("🔥 Failed to push signal:", e)

if __name__ == "__main__":
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            run_signal(sym, tf)
