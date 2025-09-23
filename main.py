# main.py (replace file in protrader-signal-worker)
import os
import json
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, firestore

import ccxt

# Optional imports (used if you enable broker SDKs)
try:
    from kiteconnect import KiteConnect
except Exception:
    KiteConnect = None
try:
    from smartapi import SmartConnect
except Exception:
    SmartConnect = None

# ------------------ CONFIG ------------------
# Admin secret for admin-only endpoints (change immediately in prod)
PTH_ADMIN_SECRET = os.environ.get("PTH_ADMIN_SECRET", "supersecret123")

# Path to service account JSON (or use env var to pass JSON string)
SERVICE_ACCOUNT_PATH = os.environ.get("SERVICE_ACCOUNT_PATH", "serviceAccount.json")

# ------------------ FIREBASE INIT ------------------
if not firebase_admin._apps:
    if os.path.exists(SERVICE_ACCOUNT_PATH):
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    else:
        # Try to read env var FIREBASE_SERVICE_ACCOUNT (JSON string)
        svc = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if not svc:
            raise RuntimeError("No Firebase service account provided (serviceAccount.json or FIREBASE_SERVICE_ACCOUNT).")
        cred = credentials.Certificate(json.loads(svc))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ------------------ FLASK APP ------------------
app = Flask(__name__)
CORS(app)


# ------------------ UTIL ------------------
def now_iso():
    return datetime.utcnow().isoformat()

def is_key_valid(doc):
    info = doc.to_dict()
    expiry = info.get("expiry")
    if not expiry:
        return True
    try:
        return datetime.utcnow() <= datetime.fromisoformat(expiry)
    except Exception:
        return False

# ------------------ PUBLIC ROUTES ------------------
@app.route("/")
def root():
    return jsonify({"message": "PTH backend running", "time": now_iso()})

# Validate key: body { "key": "<keystr>" }
@app.route("/validate_key", methods=["POST"])
def validate_key():
    data = request.json or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "No key provided"}), 400
    doc = db.collection("keys").document(key).get()
    if not doc.exists:
        return jsonify({"valid": False, "reason": "Key not found"})
    info = doc.to_dict()
    expiry = info.get("expiry")
    if expiry:
        try:
            if datetime.utcnow() > datetime.fromisoformat(expiry):
                return jsonify({"valid": False, "reason": "Expired"})
        except Exception:
            pass
    return jsonify({"valid": True, "role": info.get("role", "user"), "expiry": expiry})

# ------------------ OHLC Endpoint (for charts) ------------------
# GET /ohlc?symbol=BTC/USDT&tf=1m&limit=200
@app.route("/ohlc", methods=["GET"])
def ohlc():
    symbol = request.args.get("symbol", "BTC/USDT")
    tf = request.args.get("tf", "1m")
    limit = int(request.args.get("limit", "200"))
    try:
        exchange = ccxt.binance()
        # convert tf to ccxt timeframe (assume match)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        # ohlcv -> list of [ts, open, high, low, close, vol]
        return jsonify({"symbol": symbol, "tf": tf, "data": ohlcv})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ------------------ SIGNALS ------------------
# Worker or admin can POST a new signal to /publish_signal
# Body:
# {
#   "symbol": "BTC/USDT",
#   "signal": "BUY",
#   "meta": {...},
#   "broadcast": true  # if true, send notifications to all valid keys
# }
@app.route("/publish_signal", methods=["POST"])
def publish_signal():
    data = request.json or {}
    symbol = data.get("symbol")
    signal = data.get("signal", "INFO")
    meta = data.get("meta", {})
    broadcast = data.get("broadcast", True)

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    entry = {
        "symbol": symbol,
        "signal": signal,
        "meta": meta,
        "timestamp": now_iso()
    }
    # Save signal doc
    doc_ref = db.collection("signals").add(entry)

    # Publish notifications for all valid keys (one notification doc per key)
    if broadcast:
        keys_snap = db.collection("keys").get()
        sent = 0
        for kdoc in keys_snap:
            if is_key_valid(kdoc):
                # each notification references a key
                notif = {
                    "key": kdoc.id,
                    "signal": entry,
                    "message": f"{signal} - {symbol}",
                    "timestamp": now_iso()
                }
                db.collection("notifications").add(notif)
                sent += 1
        return jsonify({"saved": True, "sent_notifications": sent})
    return jsonify({"saved": True, "sent_notifications": 0})

# Get recent signals (public)
@app.route("/signals", methods=["GET"])
def get_signals():
    limit = int(request.args.get("limit", 50))
    snap = db.collection("signals").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit).get()
    results = []
    for d in snap:
        rec = d.to_dict()
        rec["id"] = d.id
        results.append(rec)
    return jsonify(results)

# ------------------ NOTIFICATIONS (admin-only manual broadcast) ------------------
# Admin posts to send_notification; only admin secret allowed
@app.route("/send_notification", methods=["POST"])
def send_notification():
    auth_header = request.headers.get("X-Admin-Secret", "")
    if auth_header != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json or {}
    message = data.get("message", "")
    symbol = data.get("symbol", "GENERIC")
    signal = data.get("signal", "INFO")
    price = data.get("price", "-")

    # push per-key notifications to valid keys
    keys_snap = db.collection("keys").get()
    sent = 0
    for kdoc in keys_snap:
        if is_key_valid(kdoc):
            notif = {
                "key": kdoc.id,
                "signal": {"signal": signal, "meta": {"symbol": symbol, "last_price": price}},
                "message": message,
                "timestamp": now_iso()
            }
            db.collection("notifications").add(notif)
            sent += 1
    return jsonify({"sent_to": sent})

# ------------------ TRANSACTIONS (deposit/withdraw) ------------------
# For production: expand with real ccxt trades, wallet transfers, KYC and safety checks.
# /deposit and /withdraw accept: user (email or uid), broker, amount, optional api_key & secret (or use saved credentials)
@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json or {}
    user = data.get("user", "guest")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not all([user, broker, amount]):
        return jsonify({"error": "Missing user/broker/amount"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "deposit",
        "amount": float(amount),
        "status": "processing",
        "created_at": now_iso()
    }
    ref = db.collection("transactions").add(entry)
    tx_id = ref[1].id

    # Broker handling
    try:
        if broker in ["binance", "exness"]:
            # For demo: mark completed (replace with real API transfer/chain call)
            db.collection("transactions").document(tx_id).update({"status": "completed", "completed_at": now_iso()})
            return jsonify({"tx_id": tx_id, "status": "completed"})
        elif broker in ["zerodha", "angelone"]:
            # Cannot deposit via API easily: redirect user to official site/payment
            redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in"
            db.collection("transactions").document(tx_id).update({"redirect_url": redirect_url})
            return jsonify({"tx_id": tx_id, "status": "redirect", "redirect_url": redirect_url})
        else:
            return jsonify({"tx_id": tx_id, "status": "unsupported", "message": "Unsupported broker"}), 400
    except Exception as e:
        db.collection("transactions").document(tx_id).update({"status": "failed", "error": str(e)})
        return jsonify({"tx_id": tx_id, "status": "failed", "error": str(e)}), 500

@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json or {}
    user = data.get("user", "guest")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not all([user, broker, amount]):
        return jsonify({"error": "Missing user/broker/amount"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "withdraw",
        "amount": float(amount),
        "status": "processing",
        "created_at": now_iso()
    }
    ref = db.collection("transactions").add(entry)
    tx_id = ref[1].id

    try:
        if broker in ["binance", "exness"]:
            # For demo: mark completed (replace with proper API withdraw call)
            db.collection("transactions").document(tx_id).update({"status": "completed", "completed_at": now_iso()})
            return jsonify({"tx_id": tx_id, "status": "completed"})
        elif broker in ["zerodha", "angelone"]:
            redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in"
            db.collection("transactions").document(tx_id).update({"redirect_url": redirect_url})
            return jsonify({"tx_id": tx_id, "status": "redirect", "redirect_url": redirect_url})
        else:
            return jsonify({"tx_id": tx_id, "status": "unsupported", "message": "Unsupported broker"}), 400
    except Exception as e:
        db.collection("transactions").document(tx_id).update({"status": "failed", "error": str(e)})
        return jsonify({"tx_id": tx_id, "status": "failed", "error": str(e)}), 500

# Admin: list transactions (GET), update status (PATCH)
@app.route("/transactions", methods=["GET"])
def list_transactions():
    limit = int(request.args.get("limit", "50"))
    snap = db.collection("transactions").order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit).get()
    out = []
    for d in snap:
        rec = d.to_dict()
        rec["id"] = d.id
        out.append(rec)
    return jsonify(out)

@app.route("/transactions/<txid>", methods=["PATCH"])
def patch_transaction(txid):
    auth = request.headers.get("X-Admin-Secret", "")
    if auth != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json or {}
    status = data.get("status")
    if status not in ["processing", "completed", "cancelled", "failed"]:
        return jsonify({"error": "Invalid status"}), 400
    db.collection("transactions").document(txid).update({"status": status, "updated_at": now_iso()})
    return jsonify({"updated": True})

# ------------------ CLEANUP UTILS (optional endpoints) ------------------
# Endpoint to run cleanup (admin only)
@app.route("/cleanup", methods=["POST"])
def cleanup():
    auth = request.headers.get("X-Admin-Secret", "")
    if auth != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403
    # Delete expired keys and cancel old processing txns (>7 days)
    deleted = 0
    snap = db.collection("keys").get()
    for d in snap:
        info = d.to_dict()
        exp = info.get("expiry")
        if exp:
            try:
                if datetime.utcnow() > datetime.fromisoformat(exp):
                    db.collection("keys").document(d.id).delete()
                    deleted += 1
            except Exception:
                pass
    # Cancel old processing txns older than 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)
    txsnap = db.collection("transactions").where("status", "==", "processing").get()
    cancelled = 0
    for t in txsnap:
        tdata = t.to_dict()
        created = tdata.get("created_at")
        try:
            if created and datetime.fromisoformat(created) < cutoff:
                db.collection("transactions").document(t.id).update({"status": "cancelled", "updated_at": now_iso()})
                cancelled += 1
        except Exception:
            pass
    return jsonify({"deleted_keys": deleted, "cancelled_tx": cancelled})

# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
