import os
import json
import time
import traceback
import yfinance as yf
import pandas as pd

# Load all symbols with verified timeframes
SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "symbols.json")

def load_symbols():
    with open(SYMBOLS_FILE, "r") as f:
        return json.load(f)

def map_symbol(symbol, market):
    """Map to Yahoo Finance ticker"""
    if market == "crypto":
        return symbol.replace("USDT", "-USD")
    elif market == "forex":
        return symbol + "=X"
    else:
        return symbol

def fetch_yahoo_data(symbol, market, interval, limit=200):
    yf_symbol = map_symbol(symbol, market)
    try:
        df = yf.download(
            tickers=yf_symbol,
            period="5d",
            interval=interval,
            progress=False
        )
        if df.empty:
            raise RuntimeError(f"No data received for {yf_symbol}")
        df.reset_index(inplace=True)
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                raise RuntimeError(f"Missing expected column {col} in {yf_symbol}")
        return df.tail(limit)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {yf_symbol} ({interval}): {e}")

def analyze(df):
    """Very simple signal generator (placeholder)"""
    if df["close"].iloc[-1] > df["close"].iloc[-2]:
        return "BUY"
    else:
        return "SELL"

def process_symbol(symbol_entry):
    symbol = symbol_entry["symbol"]
    market = symbol_entry.get("market", "stock")
    timeframes = symbol_entry.get("timeframes", [])

    if not timeframes:
        print(f"⚠️ No verified timeframes for {symbol}, skipping...")
        return

    for interval in timeframes:
        try:
            df = fetch_yahoo_data(symbol, market, interval=interval, limit=200)
            signal = analyze(df)
            print(f"[{symbol} | {interval}] → {signal}")
        except Exception as e:
            print(f"Error processing {symbol} {interval}: {e}")
            traceback.print_exc()

def run_worker():
    while True:
        symbols = load_symbols()
        print(f"Loaded {len(symbols)} symbols")
        for s in symbols:
            process_symbol(s)
        print("Cycle complete, sleeping 60s...\n")
        time.sleep(60)

if __name__ == "__main__":
    run_worker()
