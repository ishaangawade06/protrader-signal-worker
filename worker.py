# worker.py (Firestore-backed symbols loader)
import os, time, traceback, requests

BACKEND_URL = os.environ.get("BACKEND_URL", "https://protraderhack.onrender.com").rstrip("/")
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")

# Firestore admin
import firebase_admin
from firebase_admin import credentials, firestore

SERVICE_ACCOUNT_PATH = "serviceAccount.json"  # workflow will write this from secret

DEFAULT_INTERVALS = ["1m", "5m", "15m", "1h", "1d"]

def init_firestore():
    try:
        if not firebase_admin._apps:
            if os.path.exists(SERVICE_ACCOUNT_PATH):
                cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred)
            else:
                # If running locally and env var exists, write it
                raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
                if raw:
                    import json, base64
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        obj = json.loads(base64.b64decode(raw).decode())
                    with open(SERVICE_ACCOUNT_PATH, "w") as f:
                        f.write(json.dumps(obj))
                    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                    firebase_admin.initialize_app(cred)
                else:
                    raise RuntimeError("No Firebase service account available")
        return firestore.client()
    except Exception as e:
        print("Failed to initialize Firestore:", e)
        raise

def load_symbols_from_firestore(db):
    try:
        docs = db.collection("symbols").where("enabled", "==", True).stream()
        results = []
        for d in docs:
            data = d.to_dict()
            # Ensure minimal fields
            symbol = data.get("symbol") or d.id
            intervals = data.get("intervals") or DEFAULT_INTERVALS
            results.append({"symbol": symbol, "intervals": intervals})
        return results
    except Exception as e:
        print("Error reading symbols from Firestore:", e)
        return []

def trigger_symbol(symbol, interval):
    try:
        params = {"symbol": symbol, "interval": interval}
        url = f"{BACKEND_URL}/signal"
        r = requests.get(url, params=params, headers={"X-APP-KEY": APP_KEY}, timeout=25)
        if r.status_code == 200:
            j = r.json()
            print(f"✅ {symbol} {interval} -> {j.get('signal','?')}")
        else:
            print(f"❌ {symbol} {interval} -> {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"Error triggering {symbol} {interval}: {e}")
        traceback.print_exc()

def main():
    if not BACKEND_URL:
        raise RuntimeError("BACKEND_URL not set")
    print("🚀 Worker starting. Backend:", BACKEND_URL)

    db = init_firestore()
    syms = load_symbols_from_firestore(db)
    if not syms:
        print("⚠️ No symbols found in Firestore. Exiting.")
        return

    for entry in syms:
        symbol = entry.get("symbol")
        intervals = entry.get("intervals", DEFAULT_INTERVALS)
        for interval in intervals:
            trigger_symbol(symbol, interval)
            time.sleep(1)  # small delay to avoid overload

    print("🎯 Worker finished run.")

if __name__ == "__main__":
    main()
