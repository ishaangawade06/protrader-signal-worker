# main.py
import os, json, time, traceback
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import pandas as pd
import yfinance as yf

from auth import validate_key, db  # auth.py provides db and validate_key
from signals import hybrid_signal   # your signal engine (existing)

APP_PORT = int(os.environ.get("PORT", 5000))
SYMBOLS_FILE = "symbols.json"
CACHE_FILE = "output/timeframe_cache.json"
CACHE_TTL_DAYS = 7

os.makedirs("output", exist_ok=True)

app = Flask(__name__)

# ---------- Helpers ----------
def require_key(owner=False):
    key = request.headers.get("X-APP-KEY", "").strip()
    res = validate_key(key)
    if not res.get("valid"):
        return None, (jsonify({"error":"invalid_or_expired_key"}), 403)
    if owner and res.get("role") != "owner":
        return None, (jsonify({"error":"owner_access_required"}), 403)
    return res, None

def safe_yf_download(symbol, interval="5m", period="7d"):
    for attempt in range(3):
        try:
            df = yf.download(
                tickers=symbol,
                period=period,
                interval=interval,
                progress=False,
                threads=False,
                auto_adjust=False
            )
            if df is None or df.empty:
                time.sleep(1 + attempt)
                continue
            # flatten columns (multiindex sometimes returned)
            if isinstance(df.columns, pd.MultiIndex):
                cols = []
                for c in df.columns:
                    if isinstance(c, tuple):
                        cols.append("_".join([str(x) for x in c]).lower().replace(" ", "_"))
                    else:
                        cols.append(str(c).lower().replace(" ", "_"))
                df.columns = cols
            else:
                df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
            return df
        except Exception as e:
            print(f"[yfinance] attempt {attempt+1} failed for {symbol} {interval}: {e}")
            time.sleep(1 + attempt)
    return pd.DataFrame()

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"updated": None, "data": {}}
    return {"updated": None, "data": {}}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def cache_expired(ts):
    if not ts: return True
    try:
        last = datetime.fromisoformat(ts)
        return (datetime.utcnow() - last) > timedelta(days=CACHE_TTL_DAYS)
    except Exception:
        return True

# ---------- Endpoints ----------
@app.route("/symbols", methods=["GET"])
def api_symbols():
    res, err = require_key()
    if err: return err

    # Try Firestore collection 'symbols'
    try:
        docs = db.collection("symbols").where("enabled", "==", True).stream()
        syms = []
        for d in docs:
            data = d.to_dict()
            data['symbol'] = data.get('symbol') or d.id
            data['market'] = data.get('market', 'crypto')
            data['interval'] = data.get('interval', '1m')
            data['risk_percent'] = float(data.get('risk_percent', 2.0))
            syms.append(data)
        if syms:
            return jsonify({"symbols": syms})
    except Exception as e:
        print("Firestore /symbols read error:", e)

    # Fallback: local symbols.json
    try:
        with open(SYMBOLS_FILE, "r") as f:
            j = json.load(f)
            return jsonify(j)
    except Exception as e:
        print("Fallback symbols.json missing or invalid:", e)
        return jsonify({"symbols": []})

@app.route("/timeframes", methods=["GET"])
def api_timeframes():
    res, err = require_key()
    if err: return err
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol param required (e.g. BTC-USD)"}), 400
    refresh = request.args.get("refresh", "false").lower() == "true"
    cache = load_cache()
    key = symbol
    if not refresh and key in cache.get("data", {}) and not cache_expired(cache.get("updated")):
        return jsonify({"symbol": symbol, "timeframes": cache["data"][key], "cached": True})
    candidate_intervals = ["1m","2m","5m","15m","30m","1h","1d","1wk","1mo"]
    valid = []
    for tf in candidate_intervals:
        df = safe_yf_download(symbol, interval=tf, period="7d")
        if not df.empty:
            valid.append(tf)
    cache.setdefault("data", {})[key] = valid
    cache["updated"] = datetime.utcnow().isoformat()
    save_cache(cache)
    return jsonify({"symbol": symbol, "timeframes": valid, "cached": False})

@app.route("/history", methods=["GET"])
def api_history():
    res, err = require_key()
    if err: return err
    symbol = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "5m").strip()
    limit = int(request.args.get("limit", "500"))
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    df = safe_yf_download(symbol, interval=interval, period="30d")
    if df.empty:
        return jsonify({"error": "no data"}), 404
    df = df.tail(limit).reset_index()
    return df.to_json(orient="records")

@app.route("/signal", methods=["GET"])
def api_signal():
    user, err = require_key()
    if err: return err

    symbol = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "5m").strip()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    df = safe_yf_download(symbol, interval=interval, period="7d")
    if df.empty:
        result = {
            "symbol": symbol,
            "interval": interval,
            "signal": "HOLD",
            "reasons": ["no_data"],
            "confidence": 0.0,
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        try:
            out = hybrid_signal(df)
            result = {
                "symbol": symbol,
                "interval": interval,
                "signal": out.get("signal", "HOLD"),
                "reasons": out.get("reasons", []),
                "confidence": float(out.get("confidence", 0.0)),
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            traceback.print_exc()
            result = {
                "symbol": symbol,
                "interval": interval,
                "signal": "HOLD",
                "reasons": ["engine_error"],
                "confidence": 0.0,
                "timestamp": datetime.utcnow().isoformat()
            }

    # Store in Firestore
    try:
        db.collection("signals").add(result)
    except Exception as e:
        print("Firestore write failed:", e)

    return jsonify(result)

@app.route("/signals/history", methods=["GET"])
def api_signals_history():
    res, err = require_key()
    if err: return err

    symbol = request.args.get("symbol")
    interval = request.args.get("interval")
    limit = int(request.args.get("limit", "50"))

    try:
        query = db.collection("signals").order_by("timestamp", direction="DESCENDING")
        if symbol:
            query = query.where("symbol", "==", symbol)
        if interval:
            query = query.where("interval", "==", interval)
        docs = query.limit(limit).stream()
        signals = [d.to_dict() for d in docs]
        return jsonify({"signals": signals})
    except Exception as e:
        print("Firestore history fetch error:", e)
        return jsonify({"signals": []})

@app.route("/position-size", methods=["GET"])
def api_position_size():
    res, err = require_key()
    if err: return err
    try:
        balance = float(request.args.get("balance", "0"))
        risk = float(request.args.get("risk_percent", "1"))
        entry = float(request.args.get("entry", "0"))
        stop = float(request.args.get("stop", "0"))
        per_unit = abs(entry - stop)
        if per_unit <= 0:
            return jsonify({"error": "invalid prices"}), 400
        risk_amount = balance * (risk/100.0)
        units = risk_amount / per_unit
        return jsonify({"position_size_units": round(units, 6)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Owner endpoint (example)
@app.route("/owner/add-key", methods=["POST"])
def owner_add_key():
    res, err = require_key(owner=True)
    if err: return err
    body = request.get_json(force=True)
    key = body.get("key")
    role = body.get("role", "user")
    days = body.get("days", None)
    from auth import save_key_to_db
    save_key_to_db(key, role, days)
    return jsonify({"ok": True, "key": key})

# ---------- Run ----------
if __name__ == "__main__":
    print("Starting ProTraderHack backend.")
    app.run(host="0.0.0.0", port=APP_PORT)
