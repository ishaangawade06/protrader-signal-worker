# worker.py
import os, time, json, requests, traceback

BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")  # e.g. https://protraderhack.onrender.com
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")

def load_symbols():
    try:
        with open("symbols.json","r") as f:
            j = json.load(f)

        # If grouped (crypto/stocks/forex), flatten into one list
        symbols = []
        for group in j.values():
            if isinstance(group, list):
                for s in group:
                    if isinstance(s, dict):
                        symbols.append(s)
        return symbols

    except Exception as e:
        print("Error loading symbols.json:", e)
        return []

def trigger_symbol(sym):
    symbol = sym.get("symbol")
    interval = sym.get("interval", "1m")  # default 1m if not provided
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

    for s in syms:
        trigger_symbol(s)
        time.sleep(1)  # small delay

    print("Worker finished run successfully ✅")

if __name__ == "__main__":
    main()
