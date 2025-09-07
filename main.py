import json
import time
import ccxt
import yfinance as yf
import pandas as pd
from flask import Flask, request, jsonify

app = Flask(__name__)

# -------------------------------
# Load Symbols
# -------------------------------
with open("symbols.json", "r") as f:
    SYMBOLS = json.load(f)["symbols"]

# -------------------------------
# Fetch Yahoo Data (Stocks, Forex)
# -------------------------------
def fetch_yahoo_data(symbol, market, interval="1m", limit=200):
    yf_symbol = symbol
    if market == "crypto":
        yf_symbol = symbol.replace("USDT", "-USD")  # BTCUSDT -> BTC-USD
    elif market == "forex":
        yf_symbol = symbol + "=X"  # EURUSD -> EURUSD=X

    for attempt in range(3):
        try:
            df = yf.download(
                tickers=yf_symbol,
                period="5d",
                interval=interval,
                progress=False,
                auto_adjust=False,
            )
            if not df.empty and "Open" in df.columns:
                df = df.reset_index()
                return df
        except Exception as e:
            print(f"⚠️ Failed Yahoo fetch {yf_symbol} attempt {attempt+1}: {e}")
            time.sleep(2)

    raise RuntimeError(f"Missing expected data for {yf_symbol}")

# -------------------------------
# Fetch Crypto Data (Binance via CCXT)
# -------------------------------
def fetch_binance_data(symbol, interval="1m", limit=200):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    return df

# -------------------------------
# Detect Timeframes for a Symbol
# -------------------------------
def detect_timeframes(symbol, market):
    """
    Try fetching data on different intervals.
    Return only those that work.
    """
    test_intervals = ["1m", "5m", "15m", "1h", "4h", "1d", "1wk", "1mo"]
    valid = []

    for tf in test_intervals:
        try:
            if market == "crypto":
                df = fetch_binance_data(symbol, interval=tf, limit=10)
            else:
                df = fetch_yahoo_data(symbol, market, interval=tf, limit=10)
            if not df.empty:
                valid.append(tf)
        except Exception as e:
            print(f"Skipping {symbol} {tf}: {e}")
            continue

    return valid

# -------------------------------
# Update cached timeframes in symbols.json
# -------------------------------
def update_symbol_timeframes(symbol, market, timeframes):
    for s in SYMBOLS:
        if s["symbol"] == symbol and s.get("market") == market:
            s["timeframes"] = timeframes
    with open("symbols.json", "w") as f:
        json.dump({"symbols": SYMBOLS}, f, indent=2)

# -------------------------------
# API Endpoint: Timeframes
# -------------------------------
@app.route("/timeframes", methods=["GET"])
def timeframes():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol required (e.g. BTCUSDT or RELIANCE.NS)"}), 400

    market = request.args.get("market", "").strip().lower()
    refresh = request.args.get("refresh", "false").lower() == "true"

    if not market:
        # auto-detect from symbols.json
        for s in SYMBOLS:
            if s["symbol"] == symbol:
                market = s.get("market", "crypto")

    # If cached & refresh not requested → use directly
    for s in SYMBOLS:
        if s["symbol"] == symbol and s.get("market") == market and "timeframes" in s and not refresh:
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
        "cached": False if refresh else "updated"
    })

# -------------------------------
# Process Symbol (basic runner)
# -------------------------------
def process_symbol(symbol_data):
    symbol = symbol_data["symbol"]
    market = symbol_data.get("market", "crypto")
    interval = symbol_data.get("interval", "1m")

    print(f"Processing {symbol}...")

    try:
        if market == "crypto":
            df = fetch_binance_data(symbol, interval=interval)
        else:
            df = fetch_yahoo_data(symbol, market, interval=interval)
        print(f"✅ Got {len(df)} candles for {symbol} on {interval}")
    except Exception as e:
        print(f"❌ Error processing {symbol}: {e}")

# -------------------------------
# Main Runner
# -------------------------------
if __name__ == "__main__":
    print("Loaded symbols:", SYMBOLS)
    for sym in SYMBOLS:
        process_symbol(sym)
    app.run(host="0.0.0.0", port=5000)
