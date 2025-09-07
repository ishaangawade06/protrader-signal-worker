# main.py
import os, json, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import pandas as pd
import yfinance as yf

from signals import hybrid_signal  # from signals.py

APP_PORT = int(os.environ.get("PORT", 5000))
SYMBOLS_FILE = "symbols.json"
CACHE_FILE = "output/timeframe_cache.json"
CACHE_TTL_DAYS = 7

os.makedirs("output", exist_ok=True)

app = Flask(__name__)

# ---------- Helpers ----------
def load_symbols():
    with open(SYMBOLS_FILE, "r") as f:
        return json.load(f)

def safe_yf_download(symbol, interval="5m", period="7d"):
    """Robust yfinance fetch with retries and graceful empty returns"""
    for attempt in range(3):
        try:
            df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, threads=False)
            if df is None or df.empty:
                # small backoff and retry
                time.sleep(1 + attempt)
                continue
            # flatten columns
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
            # don't throw — log and try again
            print(f"[yfinance] attempt {attempt+1} failed for {symbol} {interval}: {e}")
            time.sleep(1 + attempt)
    # final: return empty dataframe
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
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts)
        return (datetime.utcnow() - last) > timedelta(days=CACHE_TTL_DAYS)
    except Exception:
        return True

# ---------- Endpoints ----------
@app.route("/symbols", methods=["GET"])
def api_symbols():
    data = load_symbols()
    return jsonify(data)

@app.route("/timeframes", methods=["GET"])
def api_timeframes():
    # Query params: symbol (yf format), refresh (true/false)
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol param required (e.g. BTC-USD)"}), 400
    refresh = request.args.get("refresh", "false").lower() == "true"

    cache = load_cache()
    key = symbol
    if not refresh and key in cache.get("data", {}) and not cache_expired(cache.get("updated")):
        return jsonify({"symbol": symbol, "timeframes": cache["data"][key], "cached": True})

    candidate_intervals = ["1m", "2m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]
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
    # params: symbol, interval, limit
    symbol = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "5m").strip()
    limit = int(request.args.get("limit", "500"))
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    df = safe_yf_download(symbol, interval=interval, period="30d")
    if df.empty:
        return jsonify({"error": "no data"}), 404
    # limit and return JSON records
    df = df.tail(limit).reset_index()
    return df.to_json(orient="records")

@app.route("/signal", methods=["GET"])
def api_signal():
    # params: symbol, interval
    symbol = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "5m").strip()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    df = safe_yf_download(symbol, interval=interval, period="7d")
    if df.empty:
        return jsonify({"symbol": symbol, "interval": interval, "signal": "HOLD", "reasons": ["no_data"], "confidence": 0.0})

    # produce hybrid signal using signals.hybrid_signal
    try:
        out = hybrid_signal(df)
        # ensure fields
        res = {
            "symbol": symbol,
            "interval": interval,
            "signal": out.get("signal", "HOLD"),
            "reasons": out.get("reasons", []),
            "confidence": float(out.get("confidence", 0.0)),
            "timestamp": datetime.utcnow().isoformat()
        }
        return jsonify(res)
    except Exception as e:
        print("Signal engine error:", e)
        return jsonify({"symbol": symbol, "interval": interval, "signal": "HOLD", "reasons": ["engine_error"], "confidence": 0.0})

@app.route("/position-size", methods=["GET"])
def api_position_size():
    # balance, risk_percent, entry, stop
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

# ---------- Run ----------
if __name__ == "__main__":
    print("Starting ProTraderHack backend (final).")
    app.run(host="0.0.0.0", port=APP_PORT)
