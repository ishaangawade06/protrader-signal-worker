import json
import time
import ccxt
import yfinance as yf
import pandas as pd
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# --------------------
# Load symbols
# --------------------
with open("symbols.json", "r") as f:
    SYMBOLS = json.load(f)["symbols"]

# Supported Yahoo Finance intervals
YF_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo"
]

# --------------------
# Fetch Yahoo Data
# --------------------
def fetch_yahoo_data(symbol, market, interval="1m", limit=200):
    yf_symbol = symbol
    if market == "crypto":
        yf_symbol = symbol.replace("USDT", "-USD")  # BTCUSDT -> BTC-USD
    elif market == "forex":
        yf_symbol = symbol + "=X"                   # EURUSD -> EURUSD=X

    for attempt in range(3):
        try:
            df = yf.download(
                tickers=yf_symbol,
                period="5d",
                interval=interval,
                progress=False,
                auto_adjust=False,
                prepost=False
            )
            if df is not None and not df.empty:
                df.reset_index(inplace=True)
                return df
        except Exception as e:
            print(f"⚠️ yfinance error for {yf_symbol} at {interval}: {e}")
            time.sleep(2)
    return None

# --------------------
# Fetch Binance Data
# --------------------
def fetch_binance_data(symbol, interval="1m", limit=200):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df

# --------------------
# Auto-detect valid timeframes
# --------------------
def detect_timeframes(symbol, market):
    valid = []

    if market == "crypto":
        exchange = ccxt.binance()
        markets = exchange.load_markets()
        if symbol in markets:
            valid = list(exchange.timeframes.keys())

    else:  # stocks or forex → test intervals
        for interval in YF_INTERVALS:
            df = fetch_yahoo_data(symbol, market, interval=interval, limit=50)
            if df is not None and not df.empty:
                valid.append(interval)

    return valid

# --------------------
# Save back to symbols.json
# --------------------
def update_symbol_timeframes(symbol, market, timeframes):
    updated = False
    for s in SYMBOLS:
        if s["symbol"] == symbol and s.get("market") == market:
            s["timeframes"] = timeframes
            updated = True
            break
    if updated:
        with open("symbols.json", "w") as f:
            json.dump({"symbols": SYMBOLS}, f, indent=4)

# --------------------
# Flask endpoint
# --------------------
@app.route("/timeframes", methods=["GET"])
def timeframes():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol required (e.g. BTCUSDT or RELIANCE.NS)"}), 400

    market = request.args.get("market", "").strip().lower()
    if not market:
        # auto-detect from symbols.json
        for s in SYMBOLS:
            if s["symbol"] == symbol:
                market = s.get("market", "crypto")

    # If cached → use directly
    for s in SYMBOLS:
        if s["symbol"] == symbol and s.get("market") == market and "timeframes" in s:
            return jsonify({
                "symbol": symbol,
                "market": market,
                "timeframes": s["timeframes"],
                "cached": True
            })

    # Else detect + cache
    valid_timeframes = detect_timeframes(symbol, market)
    if valid_timeframes:
        update_symbol_timeframes(symbol, market, valid_timeframes)

    return jsonify({
        "symbol": symbol,
        "market": market,
        "timeframes": valid_timeframes,
        "cached": False
    })

# --------------------
# Main Runner
# --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
