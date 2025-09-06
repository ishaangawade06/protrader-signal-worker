import json
import time
import traceback
import yfinance as yf

# -------------------------------
# Load symbols from symbols.json
# -------------------------------
def load_symbols():
    with open("symbols.json", "r") as f:
        data = json.load(f)
    return data["symbols"]

# -------------------------------
# Fetch data from Yahoo Finance
# -------------------------------
def fetch_yahoo_data(symbol, market, interval="1m", limit=200):
    # Map symbol for Yahoo Finance
    if market == "crypto":
        yf_symbol = symbol.replace("USDT", "-USD")   # BTCUSDT -> BTC-USD
    elif market == "indian":
        yf_symbol = symbol                           # RELIANCE.NS
    elif market == "forex":
        yf_symbol = symbol + "=X"                    # XAUUSD -> XAUUSD=X
    else:
        raise ValueError(f"Unsupported market: {market}")

    # Choose period based on interval
    period = "7d" if interval in ["1m", "5m", "15m"] else "1y"

    # Download data
    df = yf.download(tickers=yf_symbol, period=period, interval=interval, progress=False)

    if df.empty:
        raise RuntimeError(f"No data received for {yf_symbol}")

    # Flatten multi-index columns (e.g., ('Open','BTC-USD')) → 'open'
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]

    # Ensure required OHLCV columns exist
    expected_cols = ["open", "high", "low", "close", "volume"]
    for col in expected_cols:
        if col not in df.columns:
            raise RuntimeError(f"Missing expected column {col} in {yf_symbol}")

    return df.tail(limit)

# -------------------------------
# Process one symbol
# -------------------------------
def process_symbol(symbol_config):
    try:
        symbol = symbol_config["symbol"]
        market = symbol_config["market"]
        interval = symbol_config.get("interval", "1m")

        print(f"Processing: {symbol} ({market}, {interval})")

        # Fetch data
        df = fetch_yahoo_data(symbol, market, interval=interval, limit=200)

        # Debug: show last 2 rows
        print(df.tail(2))

        # TODO: Here you will add:
        # - Chart pattern recognition
        # - Support/Resistance levels
        # - Buy/Sell signals
        # - Capital allocation logic

    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        traceback.print_exc()

# -------------------------------
# Run worker loop
# -------------------------------
def run_worker():
    symbols = load_symbols()
    print("Loaded symbols:", symbols)

    while True:
        for sym in symbols:
            process_symbol(sym)
        print("Sleeping 30s before next run...\n")
        time.sleep(30)

# -------------------------------
# Main entry
# -------------------------------
if __name__ == "__main__":
    run_worker()
