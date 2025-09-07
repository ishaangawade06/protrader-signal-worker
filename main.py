import os
import json
import yfinance as yf
from datetime import datetime
import time

# Path to symbols.json
SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "symbols.json")

# Valid Yahoo Finance intervals
VALID_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo"
]

def load_symbols():
    """Load symbols.json file"""
    with open(SYMBOLS_FILE, "r") as f:
        return json.load(f)

def save_symbols(data):
    """Save back to symbols.json file"""
    with open(SYMBOLS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def map_symbol(symbol, market):
    """Map user symbol to Yahoo Finance ticker"""
    if market == "crypto":
        return symbol.replace("USDT", "-USD")
    elif market == "forex":
        return symbol + "=X"
    else:
        return symbol  # stocks already valid e.g. RELIANCE.NS

def fetch_data(symbol, market, interval="1h", period="5d"):
    """Download data from Yahoo Finance"""
    yf_symbol = map_symbol(symbol, market)
    try:
        df = yf.download(
            tickers=yf_symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False
        )
        if df.empty:
            raise RuntimeError(f"No data for {symbol} ({interval})")
        return df
    except Exception as e:
        print(f"❌ Failed to get {symbol} ({interval}): {e}")
        return None

def process_symbol(symbol_obj):
    """Process each symbol across all available valid timeframes"""
    symbol = symbol_obj["symbol"]
    market = symbol_obj.get("market", "stock")
    intervals = symbol_obj.get("timeframes") or [symbol_obj.get("interval", "1h")]

    print(f"\n=== Processing {symbol} ({market}) ===")
    for interval in intervals:
        if interval not in VALID_INTERVALS:
            print(f"⚠ Skipping unsupported interval '{interval}' for {symbol}")
            continue

        df = fetch_data(symbol, market, interval=interval, period="5d")
        if df is None:
            continue

        print(f"✔ {symbol} [{interval}] data points: {len(df)}")
        # 🔹 Insert your indicator/signal logic here

def run():
    symbols = load_symbols()
    print("Loaded symbols:", symbols)

    for symbol_obj in symbols:
        try:
            process_symbol(symbol_obj)
        except Exception as e:
            print(f"Error processing {symbol_obj['symbol']}: {e}")

if __name__ == "__main__":
    while True:
        run()
        print(f"Cycle completed @ {datetime.utcnow()}")
        time.sleep(60)  # wait 1 minute before next cycle
