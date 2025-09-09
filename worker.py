# worker.py
import os, time, json, requests, traceback

BACKEND_URL = os.environ.get("BACKEND_URL", "https://protraderhack.onrender.com").rstrip("/")
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")

# Default intervals for every symbol
DEFAULT_INTERVALS = ["1m", "5m", "15m", "1h", "1d"]

def load_symbols():
    """Load symbols.json (crypto, stocks, forex) into a flat list."""
    try:
        with open("symbols.json","r") as f:
            j = json.load(f)
        symbols = []
        for cat, arr in j.items():
            for s in arr:
                symbols.append(s.get("symbol"))
        return symbols
    except Exception as e:
        print("Error loading symbols.json:", e)
        return []

def trigger_symbol(symbol, interval):
    """Call backend /signal for one symbol + interval."""
    try:
        params = {"symbol": symbol, "interval": interval}
        url = f"{BACKEND_URL}/signal"
        r = requests.get(url, params=params, headers={"X-APP-KEY": APP_KEY}, timeout=20)
        if r.status_code == 200:
            print(f"✅ {symbol} {interval} -> {r.json().get('signal')}")
        else:
            print(f"❌ {symbol} {interval} -> {r.status_code}")
    except Exception as e:
        print(f"Error triggering {symbol} {interval}: {e}")
        traceback.print_exc()

def main():
    if not BACKEND_URL:
        raise RuntimeError("BACKEND_URL not set")
    print("🚀 Worker started. Backend:", BACKEND_URL)

    syms = load_symbols()
    if not syms:
        print("⚠️ No symbols found. Exiting.")
        return

    for symbol in syms:
        for interval in DEFAULT_INTERVALS:
            trigger_symbol(symbol, interval)
            time.sleep(1)  # avoid API overload

    print("🎯 Worker finished run successfully ✅")

if __name__ == "__main__":
    main()
