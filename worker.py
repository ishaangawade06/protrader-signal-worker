# worker.py
import os, time, json, requests, traceback

BACKEND_URL = os.environ.get("BACKEND_URL", "https://protraderhack.onrender.com").rstrip("/")
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")
SLEEP_SECONDS = int(os.environ.get("WORKER_SLEEP", "30"))

def fetch_symbols_from_backend():
    try:
        url = f"{BACKEND_URL}/symbols"
        r = requests.get(url, headers={"X-APP-KEY": APP_KEY}, timeout=20)
        if r.status_code != 200:
            print("Failed to fetch symbols, status:", r.status_code, r.text)
            return []
        j = r.json()
        return j.get("symbols", []) or []
    except Exception as e:
        print("Error fetching symbols:", e)
        traceback.print_exc()
        return []

def trigger_symbol(sym):
    try:
        symbol = sym.get("symbol")
        interval = sym.get("interval", "1m")
        params = {"symbol": symbol, "interval": interval}
        url = f"{BACKEND_URL}/signal"
        r = requests.get(url, params=params, headers={"X-APP-KEY": APP_KEY}, timeout=20)
        print("Triggered", symbol, interval, "->", r.status_code, r.text[:200])
    except Exception as e:
        print("Error triggering", sym, e)
        traceback.print_exc()

def main():
    print("Worker started. Backend:", BACKEND_URL)
    syms = fetch_symbols_from_backend()
    if not syms:
        print("No symbols found. Exiting.")
        return
    for s in syms:
        trigger_symbol(s)
        time.sleep(0.5)
    print("Worker finished run successfully ✅")

if __name__ == "__main__":
    main()
