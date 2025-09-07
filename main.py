import json
import time
import ccxt
import yfinance as yf
import pandas as pd

# ----------------------------
# Load Symbols
# ----------------------------
with open("symbols.json", "r") as f:
    SYMBOLS = json.load(f)["symbols"]

# ----------------------------
# Fetch Yahoo Data (Stocks, Forex)
# ----------------------------
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
                threads=False,
            )
            if not df.empty:
                df = df.rename(columns={str(c).lower(): str(c).lower() for c in df.columns})
                for col in ["open", "high", "low", "close"]:
                    if col not in df.columns:
                        raise RuntimeError(f"Missing expected column {col} in {yf_symbol}")
                return df
        except Exception as e:
            print(f"[Retry {attempt+1}] Failed to fetch {yf_symbol}: {e}")
        time.sleep(2)

    raise RuntimeError(f"Yahoo Finance failed after retries for {yf_symbol}")

# ----------------------------
# Fetch Crypto Data (Binance)
# ----------------------------
def fetch_binance_data(symbol, interval="1m", limit=200):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol.replace("USDT", "/USDT"), timeframe=interval, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df

# ----------------------------
# Process Symbol
# ----------------------------
def process_symbol(symbol_data):
    symbol = symbol_data["symbol"]
    market = symbol_data.get("market", "crypto")
    interval = symbol_data.get("interval", "1m")

    print(f"Processing {symbol} ({market})...")

    try:
        if market == "crypto":
            df = fetch_binance_data(symbol, interval=interval)
        else:
            df = fetch_yahoo_data(symbol, market, interval=interval)

        print(f"✅ Got {len(df)} candles for {symbol} on {interval}")
    except Exception as e:
        print(f"❌ Error processing {symbol}: {e}")

# ----------------------------
# Main Runner
# ----------------------------
if __name__ == "__main__":
    print("Loaded symbols:", SYMBOLS)
    for sym in SYMBOLS:
        process_symbol(sym)
