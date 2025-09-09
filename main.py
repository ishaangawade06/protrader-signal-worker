# main.py
import os, json, time, traceback
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g
import pandas as pd
import yfinance as yf
import requests

from signals import hybrid_signal     # you already have this
import auth                            # the auth.py we placed

# Optional firebase admin messaging if available (for FCM)
_firebase_messaging_available = False
try:
    import firebase_admin
    from firebase_admin import messaging
    _firebase_messaging_available = True
except Exception:
    _firebase_messaging_available = False

APP_PORT = int(os.environ.get("PORT", 5000))
SYMBOLS_FILE = "symbols.json"
CACHE_FILE = "output/timeframe_cache.json"
CACHE_TTL_DAYS = int(os.environ.get("CACHE_TTL_DAYS", "7"))

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
                time.sleep(1 + attempt)
                continue
            # normalize columns
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
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts)
        return (datetime.utcnow() - last) > timedelta(days=CACHE_TTL_DAYS)
    except Exception:
        return True

# ---------- Firebase helpers (if available from auth._get_db) ----------
def _get_db():
    try:
        db = auth._get_db()  # auth exposes _get_db() if firebase was initialized
        return db
    except Exception:
        return None

def save_signal_to_firestore(doc):
    db = _get_db()
    if not db:
        return False
    try:
        db.collection("signals").add(doc)
        return True
    except Exception as e:
        print("save_signal_to_firestore error:", e)
        return False

def send_fcm(title, body, data=None, topic=None):
    if not _firebase_messaging_available:
        return False
    try:
        if topic is None:
            topic = os.environ.get("FCM_TOPIC","signals")
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic=topic,
            data=data or {}
        )
        resp = messaging.send(msg)
        print("FCM sent:", resp)
        return True
    except Exception as e:
        print("FCM error:", e)
        return False

# ---------- Auth Middleware ----------
@app.before_request
def authenticate():
    # Allow open endpoints (health, root, admin auth when protected separate)
    open_endpoints = ["health", "root", "static"]
    if request.endpoint in open_endpoints:
        return None

    # If maintenance mode enabled (stored in Firestore settings), block non-owner users
    db = _get_db()
    maintenance = False
    if db:
        try:
            doc = db.collection("settings").document("maintenance").get()
            if doc.exists and doc.to_dict().get("enabled", False):
                maintenance = True
        except Exception:
            maintenance = False
    # check owner override
    key = request.headers.get("X-API-KEY", "").strip()
    valid, role, exp = auth.check_key(key)
    # Device blocking: check header X-DEVICE-ID
    device_id = request.headers.get("X-DEVICE-ID","").strip()
    if auth.is_device_blocked(device_id):
        return jsonify({"error": "device_blocked"}), 403
    # Log access attempt
    meta = {
        "path": request.path,
        "method": request.method,
        "ip": request.remote_addr,
        "ua": request.headers.get("User-Agent",""),
        "device_id": device_id
    }
    auth.log_usage(key or "anonymous", "request", meta)

    # If request is to admin endpoints, we check admin pass & owner inside routes directly
    # For protected API endpoints (signals etc.) require valid key
    protected = ["/symbols","/timeframes","/history","/signal","/position-size","/account","/account/"]
    # simpler: require key for main API endpoints (by endpoint name)
    protected_endpoints = ["api_symbols","api_timeframes","api_history","api_signal","api_position_size"]
    if request.endpoint in protected_endpoints:
        if not valid:
            return jsonify({"error": "invalid_or_expired_key"}), 403
        # if maintenance and not owner, block
        if maintenance and role != "owner":
            return jsonify({"error": "maintenance_mode"}), 503
        # attach role/expiry to request context
        g.role = role
        g.key = key
        g.key_expires = exp
    # otherwise allow; admin endpoints will do their own checks

# ---------- Endpoints ----------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status":"ok","note":"ProTraderHack backend"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok", "time": datetime.utcnow().isoformat()})

@app.route("/auth/validate", methods=["GET"])
def auth_validate():
    key = request.headers.get("X-API-KEY","").strip()
    valid, role, exp = auth.check_key(key)
    return jsonify({"valid": valid, "role": role, "expiry": exp})

# ---- Admin endpoints (owner or admin-pass) ----
def _admin_auth_ok():
    # Accept if X-API-KEY is owner OR X-ADMIN-PASS matches stored admin pass
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if ok and role == "owner":
        return True
    admin_pass = request.headers.get("X-ADMIN-PASS","").strip()
    if admin_pass and admin_pass == auth.get_admin_password():
        return True
    return False

@app.route("/admin/create-key", methods=["POST"])
def admin_create_key():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    body = request.get_json() or {}
    key = body.get("key")
    days = int(body.get("days", 0))
    if not key:
        return jsonify({"error":"key required"}), 400
    created_by = request.headers.get("X-API-KEY","admin-pass")
    ok = auth.create_key(key, days, creator=created_by)
    return jsonify({"ok": bool(ok)})

@app.route("/admin/delete-key", methods=["POST"])
def admin_delete_key():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    body = request.get_json() or {}
    key = body.get("key")
    if not key:
        return jsonify({"error":"key required"}), 400
    ok = auth.delete_key(key)
    return jsonify({"ok": bool(ok)})

@app.route("/admin/list-keys", methods=["GET"])
def admin_list_keys():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    keys = auth.list_keys()
    return jsonify({"keys": keys})

@app.route("/admin/set-admin-pass", methods=["POST"])
def admin_set_admin_pass():
    # only owner can change admin pass
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if not (ok and role == "owner"):
        return jsonify({"error":"owner_required"}), 403
    body = request.get_json() or {}
    newpass = body.get("password")
    if not newpass:
        return jsonify({"error":"password required"}), 400
    auth.set_admin_password(newpass)
    return jsonify({"ok": True})

@app.route("/admin/block-device", methods=["POST"])
def admin_block_device():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    body = request.get_json() or {}
    device_id = body.get("device_id")
    reason = body.get("reason","")
    if not device_id:
        return jsonify({"error":"device_id required"}), 400
    auth.block_device(device_id, reason)
    return jsonify({"ok": True})

@app.route("/admin/unblock-device", methods=["POST"])
def admin_unblock_device():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    body = request.get_json() or {}
    device_id = body.get("device_id")
    if not device_id:
        return jsonify({"error":"device_id required"}), 400
    auth.unblock_device(device_id)
    return jsonify({"ok": True})

@app.route("/admin/set-maintenance", methods=["POST"])
def admin_set_maintenance():
    if not _admin_auth_ok():
        return jsonify({"error":"not_authorized"}), 403
    body = request.get_json() or {}
    enabled = bool(body.get("enabled", False))
    db = _get_db()
    if db:
        db.collection("settings").document("maintenance").set({"enabled": enabled, "ts": datetime.utcnow().isoformat()})
        return jsonify({"ok": True})
    return jsonify({"error":"no_db"}), 500

# ---------- Account endpoints ----------
@app.route("/account/connect", methods=["POST"])
def account_connect():
    # user must be authenticated by middleware (X-API-KEY)
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if not ok:
        return jsonify({"error":"invalid_key"}), 403
    body = request.get_json() or {}
    broker = body.get("broker")
    api_key = body.get("api_key")
    api_secret = body.get("api_secret")
    extra = body.get("extra", {})
    if not broker or not api_key or not api_secret:
        return jsonify({"error":"broker/api_key/api_secret required"}), 400
    db = _get_db()
    record = {
        "key": key,
        "broker": broker,
        "api_key": api_key,
        "api_secret": api_secret,
        "extra": extra,
        "connected_at": datetime.utcnow().isoformat()
    }
    if db:
        db.collection("connections").document(f"{key}_{broker}").set(record)
        return jsonify({"ok": True})
    # local fallback - append into local keys file (not recommended)
    local = auth._load_local_keys()
    conns = local.get("_connections", {})
    conns[f"{key}_{broker}"] = record
    local["_connections"] = conns
    auth._save_local_keys(local)
    return jsonify({"ok": True})

@app.route("/account/disconnect", methods=["POST"])
def account_disconnect():
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if not ok:
        return jsonify({"error":"invalid_key"}), 403
    body = request.get_json() or {}
    broker = body.get("broker")
    if not broker:
        return jsonify({"error":"broker required"}), 400
    db = _get_db()
    docid = f"{key}_{broker}"
    if db:
        db.collection("connections").document(docid).delete()
        return jsonify({"ok": True})
    local = auth._load_local_keys()
    conns = local.get("_connections", {})
    if docid in conns:
        del conns[docid]
        local["_connections"] = conns
        auth._save_local_keys(local)
    return jsonify({"ok": True})

@app.route("/account/list", methods=["GET"])
def account_list():
    # list current user's connections
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if not ok:
        return jsonify({"error":"invalid_key"}), 403
    db = _get_db()
    out = []
    if db:
        docs = db.collection("connections").where("key","==",key).stream()
        for d in docs:
            rec = d.to_dict()
            rec["_id"] = d.id
            # mask secret
            if "api_secret" in rec:
                rec["api_secret_masked"] = rec["api_secret"][:4] + "..." 
                del rec["api_secret"]
            out.append(rec)
        return jsonify({"connections": out})
    # local fallback
    local = auth._load_local_keys()
    conns = local.get("_connections",{})
    for k,v in conns.items():
        if v.get("key")==key:
            vv = dict(v)
            vv["api_secret_masked"] = vv["api_secret"][:4] + "..." 
            del vv["api_secret"]
            vv["_id"] = k
            out.append(vv)
    return jsonify({"connections": out})

@app.route("/account/balance", methods=["GET"])
def account_balance():
    # example: /account/balance?broker=binance
    key = request.headers.get("X-API-KEY","").strip()
    ok, role, _ = auth.check_key(key)
    if not ok:
        return jsonify({"error":"invalid_key"}), 403
    broker = request.args.get("broker","").strip().lower()
    if not broker:
        return jsonify({"error":"broker required"}), 400
    db = _get_db()
    conn = None
    docid = f"{key}_{broker}"
    if db:
        doc = db.collection("connections").document(docid).get()
        if doc.exists:
            conn = doc.to_dict()
    else:
        local = auth._load_local_keys()
        conn = local.get("_connections", {}).get(docid)
    if not conn:
        return jsonify({"error":"not_connected"}), 404

    # Binance: get spot account balances (requires signature)
    if broker == "binance":
        try:
            api_key = conn["api_key"]
            api_secret = conn["api_secret"]
            ts = int(time.time()*1000)
            query = f"timestamp={ts}"
            import hmac, hashlib
            sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            url = f"https://api.binance.com/api/v3/account?{query}&signature={sig}"
            headers = {"X-MBX-APIKEY": api_key}
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            # return balances with non-zero
            balances = [b for b in data.get("balances", []) if float(b.get("free","0"))>0 or float(b.get("locked","0"))>0]
            return jsonify({"balances": balances})
        except Exception as e:
            print("binance balance error:", e)
            return jsonify({"error":"binance_error", "detail": str(e)}), 500

    # Exness placeholder: Exness API differs; return stored extra if present
    if broker == "exness":
        return jsonify({"info": "Exness balance API integration requires user's API and mapping. Stored connection: ", "connection": {"extra": conn.get("extra")}})

    # fallback: return stored connection info (masked)
    masked = dict(conn)
    if "api_secret" in masked:
        masked["api_secret_masked"] = masked["api_secret"][:4] + "..."
        del masked["api_secret"]
    if "api_key" in masked:
        masked["api_key_masked"] = masked["api_key"][:6] + "..."
        del masked["api_key"]
    return jsonify({"connection": masked})

# ---------- Symbols, timeframes, history, signal ----------
@app.route("/symbols", methods=["GET"])
def api_symbols():
    return jsonify(load_symbols())

@app.route("/timeframes", methods=["GET"])
def api_timeframes():
    symbol = request.args.get("symbol","").strip()
    if not symbol:
        return jsonify({"error":"symbol required"}), 400
    refresh = request.args.get("refresh","false").lower()=="true"
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
    symbol = request.args.get("symbol","").strip()
    interval = request.args.get("interval","5m").strip()
    limit = int(request.args.get("limit","500"))
    if not symbol:
        return jsonify({"error":"symbol required"}), 400
    df = safe_yf_download(symbol, interval=interval, period="30d")
    if df.empty:
        return jsonify({"error":"no data"}), 404
    df = df.tail(limit).reset_index()
    return df.to_json(orient="records")

@app.route("/signal", methods=["GET"])
def api_signal():
    symbol = request.args.get("symbol","").strip()
    interval = request.args.get("interval","5m").strip()
    if not symbol:
        return jsonify({"error":"symbol required"}), 400
    df = safe_yf_download(symbol, interval=interval, period="7d")
    if df.empty:
        return jsonify({"symbol": symbol, "interval": interval, "signal": "HOLD", "reasons":["no_data"], "confidence": 0.0})
    try:
        out = hybrid_signal(df)
        res = {
            "symbol": symbol,
            "interval": interval,
            "signal": out.get("signal", "HOLD"),
            "reasons": out.get("reasons", []),
            "confidence": float(out.get("confidence", 0.0)) if out.get("confidence") is not None else 0.0,
            "timestamp": datetime.utcnow().isoformat(),
            "last_price": float(df['close'].iloc[-1]) if 'close' in df.columns and not df['close'].empty else None
        }
        # Save to Firestore if configured
        try:
            save_signal_to_firestore(res)
        except Exception as e:
            print("save_signal failed:", e)
        # send FCM for BUY/SELL
        if res["signal"] in ("BUY","SELL"):
            try:
                title = f"ProTraderHack {res['signal']} {symbol}"
                body = f"{res['signal']} {symbol} @ {res.get('last_price')} {', '.join(res.get('reasons',[]))}"
                send_fcm(title, body, data={"symbol": symbol, "signal": res["signal"]})
            except Exception as e:
                print("FCM send error:", e)
        return jsonify(res)
    except Exception as e:
        print("Signal engine error:", e)
        traceback.print_exc()
        return jsonify({"symbol": symbol, "interval": interval, "signal": "HOLD", "reasons": ["engine_error"], "confidence": 0.0})

@app.route("/position-size", methods=["GET"])
def api_position_size():
    try:
        balance = float(request.args.get("balance","0"))
        risk = float(request.args.get("risk_percent","1"))
        entry = float(request.args.get("entry","0"))
        stop = float(request.args.get("stop","0"))
        per_unit = abs(entry - stop)
        if per_unit <= 0:
            return jsonify({"error":"invalid prices"}), 400
        risk_amount = balance * (risk/100.0)
        units = risk_amount / per_unit
        return jsonify({"position_size_units": round(units,6)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- Run ----------
if __name__ == "__main__":
    print("Starting ProTraderHack backend (with admin & auth).")
    app.run(host="0.0.0.0", port=APP_PORT)
