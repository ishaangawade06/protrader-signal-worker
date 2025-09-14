# main.py
import os, json, time, traceback
from datetime import datetime
import pandas as pd
import yfinance as yf

import firebase_admin
from firebase_admin import credentials, firestore, messaging

from signals import hybrid_signal

# ENV / config
FIREBASE_SERVICE_ACCOUNT_ENV = "FIREBASE_SERVICE_ACCOUNT"  # set this to the service account JSON (string) in secrets
APP_KEY = os.environ.get("PROTRADER_APP_KEY", "ishaan")
FCM_TOPIC = os.environ.get("FCM_TOPIC", "signals")
SYMBOLS_FILE = "symbols.json"   # local fallback symbol list
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_SECONDS", "30"))

# init firebase
def init_firebase():
    raw = os.environ.get(FIREBASE_SERVICE_ACCOUNT_ENV)
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT env missing")
    try:
        sa = json.loads(raw)
    except Exception:
        import base64
        sa = json.loads(base64.b64decode(raw).decode())
    cred = credentials.Certificate(sa)
    firebase_admin.initialize_app(cred)
    return firestore.client()

def safe_yf_download(symbol, interval="5m", period="7d"):
    # Map common symbols to yfinance if needed already provided by user
    # Use retries
    for attempt in range(3):
        try:
            df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, threads=False, auto_adjust=False)
            if df is None or df.empty:
                time.sleep(1 + attempt)
                continue
            # flatten columns if needed
            if isinstance(df.columns, pd.MultiIndex):
                cols = []
                for c in df.columns:
                    cols.append("_".join([str(x) for x in c]).lower().replace(" ", "_"))
                df.columns = cols
            else:
                df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
            # keep required columns
            df = df.dropna(subset=['close'])
            return df
        except Exception as e:
            print("yfinance attempt", attempt, "failed", symbol, interval, e)
            time.sleep(1 + attempt)
    return pd.DataFrame()

def load_symbols():
    if os.path.exists(SYMBOLS_FILE):
        try:
            with open(SYMBOLS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # fallback default list (small)
    return {
        "crypto": [{"symbol":"BTC-USD"},{"symbol":"ETH-USD"}],
        "stocks": [{"symbol":"RELIANCE.NS"}],
        "forex": [{"symbol":"XAUUSD=X"}]
    }

def send_fcm_notification(title, body, data=None, topic=None):
    try:
        if topic is None:
            topic = FCM_TOPIC
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic=topic,
            data=data or {}
        )
        resp = messaging.send(message)
        print("FCM sent:", resp)
    except Exception as e:
        print("FCM error:", e)

def main_loop():
    db = init_firebase()
    symbols_obj = load_symbols()
    # flatten symbols from categories
    symbols = []
    for cat, arr in symbols_obj.items():
        for s in arr:
            if isinstance(s, dict):
                symbols.append(s.get("symbol"))
            else:
                symbols.append(str(s))
    print("Monitoring symbols:", symbols)

    while True:
        for sym in symbols:
            try:
                # run on 5m timeframe by default; you can change per-symbol later
                df = safe_yf_download(sym, interval="5m", period="7d")
                if df.empty:
                    print("No data for", sym)
                    continue
                out = hybrid_signal(df)
                # prepare payload
                payload = {
                    "symbol": sym,
                    "signal": out['signal'],
                    "confidence": float(out['confidence']),
                    "reasons": out.get('reasons', []),
                    "meta": out.get('meta', {}),
                    "generated_at": datetime.utcnow().isoformat()
                }
                # store in Firestore signals collection
                try:
                    db.collection("signals").add(payload)
                    print("Saved signal:", sym, payload['signal'], payload['confidence'])
                except Exception as e:
                    print("Firestore write error:", e)
                # notify only for buy/sell strong signals
                if out['signal'] in ("BUY", "SELL") and out['confidence'] >= 0.5:
                    title = f"PTH {out['signal']} {sym}"
                    body = f"{out['signal']} {sym} @ {payload['meta'].get('last_price')} ({out['confidence']*100:.0f}%)"
                    # global topic
                    send_fcm_notification(title, body, data={"symbol": sym, "signal": out['signal']})
                    # symbol-specific topic (safe name)
                    topic_safe = ("signals_" + sym.replace(".", "_").replace("/", "_")).lower()
                    send_fcm_notification(title, body, data={"symbol": sym, "signal": out['signal']}, topic=topic_safe)
            except Exception as e:
                print("Error processing", sym, e)
                traceback.print_exc()
            time.sleep(0.5)  # small gap between symbols
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("Starting ProTraderHack signal worker")
    main_loop()
