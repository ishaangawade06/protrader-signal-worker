# worker.py
import os, time, json, requests, traceback

# <<< EDIT: point to your deployed backend URL here >>>
BACKEND_URL = os.environ.get("BACKEND_URL", "https://protraderhack.onrender.com").rstrip("/")
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")
SLEEP_SECONDS = int(os.environ.get("WORKER_SLEEP", "30"))

def load_symbols():
    try:
        with open("symbols.json","r") as f:
            j = json.load(f)
        symbols = []
        for cat, arr in j.items():
            for s in arr:
                symbols.append(s)
        return symbols
    except Exception as e:
        print("Error loading symbols.json:", e)
        return []

def trigger_symbol(symbol, interval):
    try:
        params = {"symbol": symbol, "interval": interval}
        url = f"{BACKEND_URL}/signal"
        r = requests.get(url, params=params, headers={"X-APP-KEY": APP_KEY}, timeout=20)
        print("Triggered", symbol, interval, "->", r.status_code)
    except Exception as e:
        print("Error triggering", symbol, e)
        traceback.print_exc()

def main():
    if not BACKEND_URL:
        raise RuntimeError("BACKEND_URL not set")
    print("Worker started. Backend:", BACKEND_URL)
    syms = load_symbols()
    if not syms:
        print("No symbols found. Exiting.")
        return
    default_intervals = ["1m","5m","15m","1h","1d"]
    for s in syms:
        symbol = s.get("symbol") if isinstance(s, dict) else s
        for interval in default_intervals:
            trigger_symbol(symbol, interval)
            time.sleep(1)
    print("Worker finished run successfully ✅")

if __name__ == "__main__":
    main()
