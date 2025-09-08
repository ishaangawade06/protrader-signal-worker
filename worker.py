# worker.py
import os, time, json, requests, traceback

BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")  # e.g. https://your-app.onrender.com
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")
SLEEP_SECONDS = int(os.environ.get("WORKER_SLEEP", "30"))

def load_symbols():
    with open("symbols.json","r") as f:
        j = json.load(f)
    return j.get("symbols", [])

def trigger_symbol(sym):
    try:
        symbol = sym.get("symbol")
        interval = sym.get("interval","1m")
        params = {"symbol": symbol, "interval": interval}
        url = f"{BACKEND_URL}/signal"
        r = requests.get(url, params=params, headers={"X-APP-KEY": APP_KEY}, timeout=15)
        print("Triggered", symbol, r.status_code)
    except Exception as e:
        print("Err trigger", symbol, e)
        traceback.print_exc()

def main():
    if not BACKEND_URL:
        raise RuntimeError("BACKEND_URL not set")
    print("Worker started. Backend:", BACKEND_URL)
    while True:
        syms = load_symbols()
        for s in syms:
            trigger_symbol(s)
            time.sleep(0.5)
        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()
