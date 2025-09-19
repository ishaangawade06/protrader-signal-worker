# signal_worker.py
import ccxt
import pandas as pd
import time
import firebase_admin
from firebase_admin import credentials, firestore
from signals import hybrid_signal   # your strategy file

# 🔑 Firebase setup
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Exchange setup (Binance)
exchange = ccxt.binance()

symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
timeframes = ["1m", "5m", "15m", "1h", "1d"]

def fetch_candles(symbol, tf="5m", limit=120):
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df

def run_signals():
    while True:
        for symbol in symbols:
            results = []
            decision = "HOLD"
            reasons = []

            for tf in timeframes:
                try:
                    df = fetch_candles(symbol, tf, limit=150)
                    sig = hybrid_signal(df)
                    results.append(sig["signal"])
                    reasons.extend([f"{tf}:{r}" for r in sig["reasons"]])
                except Exception as e:
                    print(f"⚠️ Error fetching {symbol} {tf}: {e}")

            if results:
                # majority vote across timeframes
                decision = max(set(results), key=results.count)

                # get last price from the last dataframe
                price = float(df["close"].iloc[-1])

                signal_doc = {
                    "symbol": symbol,
                    "type": decision,
                    "price": price,
                    "time": int(time.time()*1000),
                    "reasons": results,
                    "details": reasons
                }

                db.collection("signals").add(signal_doc)
                print(f"📢 {symbol} → {decision} @ {price} ({results})")

        time.sleep(60)  # run every 1 min

if __name__ == "__main__":
    run_signals()
