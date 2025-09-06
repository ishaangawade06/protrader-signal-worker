import yfinance as yf
import pandas as pd
import json
import time
from datetime import datetime
import os

# Load symbols
with open("symbols.json", "r") as f:
    SYMBOLS = json.load(f)

def fetch_yahoo_data(symbol, market, interval="1h", limit=200):
    try:
        df = yf.download(symbol, period="60d", interval=interval, progress=False)

        if df is None or df.empty:
            print(f"❌ No data received for {symbol}")
            return None

        df.reset_index(inplace=True)
        df = df.tail(limit)
        return df
    except Exception as e:
        print(f"⚠️ Failed to fetch {symbol}: {e}")
        return None

def process_symbol(symbol, market, interval="1h"):
    df = fetch_yahoo_data(symbol, market, interval=interval, limit=200)
    if df is None:
        return None

    try:
        output_dir = "data"
        os.makedirs(output_dir, exist_ok=True)

        file_path = os.path.join(output_dir, f"{market}_{symbol.replace('=', '').replace('-', '')}.csv")
        df.to_csv(file_path, index=False)

        print(f"✅ Saved {symbol} ({market}) -> {file_path}")
        return file_path
    except Exception as e:
        print(f"⚠️ Error saving {symbol}: {e}")
        return None

def main():
    while True:
        print(f"\n🔄 Running fetch at {datetime.now()}")

        for market, symbols in SYMBOLS.items():
            for symbol in symbols:
                process_symbol(symbol, market, interval="1h")

        print("⏳ Sleeping for 5 minutes...\n")
        time.sleep(300)

if __name__ == "__main__":
    main()
