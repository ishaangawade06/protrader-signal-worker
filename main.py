# main.py  -- replace in protrader-signal-worker
import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

# optional dependencies: ccxt used for OHLC
try:
    import ccxt
except Exception:
    ccxt = None

# Firebase admin
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- config ----------
PTH_ADMIN_SECRET = os.environ.get("PTH_ADMIN_SECRET", "supersecret123")
SERVICE_ACCOUNT_PATH = os.environ.get("SERVICE_ACCOUNT_PATH", "serviceAccount.json")
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")  # optional JSON string
PORT = int(os.environ.get("PORT", 5000))

# ---------- firebase init ----------
if not firebase_admin._apps:
    if os.path.exists(SERVICE_ACCOUNT_PATH):
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    elif FIREBASE_SERVICE_ACCOUNT:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT))
    else:
        raise RuntimeError("No Firebase service account found. Set serviceAccount.json or FIREBASE_SERVICE_ACCOUNT env.")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- app ----------
app = Flask(__name__)
CORS(app)


def now_iso():
    return datetime.utcnow().isoformat()


def is_key_valid_doc(kdoc):
    info = kdoc.to_dict() or {}
    expiry = info.get("expiry")
    if not expiry:
        return True
    try:
        return datetime.utcnow() <= datetime.fromisoformat(expiry)
    except Exception:
        return True


# ---------- root ----------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "protrader-backend", "time": now_iso()})


# ---------- key validation ----------
@app.route("/validate_key", methods=["POST"])
def validate_key():
    data = request.json or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "key missing"}), 400
    doc = db.collection("keys").document(key).get()
    if not doc.exists:
        return jsonify({"valid": False, "reason": "Key not found"})
    info = doc.to_dict() or {}
    expiry = info.get("expiry")
    if expiry:
        try:
            if datetime.utcnow() > datetime.fromisoformat(expiry):
                return jsonify({"valid": False, "reason": "Expired"})
        except Exception:
            pass
    return jsonify({"valid": True, "role": info.get("role", "user"), "expiry": expiry})


# ---------- OHLC for charts ----------
@app.route("/ohlc", methods=["GET"])
def ohlc():
    symbol = request.args.get("symbol", "BTC/USDT")
    tf = request.args.get("tf", "1m")
    limit = int(request.args.get("limit", 200))
    if ccxt is None:
        return jsonify({"error": "ccxt not installed on server"}), 500
    try:
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        return jsonify({"symbol": symbol, "tf": tf, "data": ohlcv})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------- publish signal (worker/admin) ----------
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
    db.collection("signals").add(entry)

    sent = 0
    if broadcast:
        keys_snap = db.collection("keys").get()
        for kd in keys_snap:
            if is_key_valid_doc(kd):
                notif = {
                    "key": kd.id,
                    "signal": entry,
                    "message": f"{signal} - {symbol}",
                    "timestamp": now_iso()
                }
                db.collection("notifications").add(notif)
                sent += 1
    return jsonify({"saved": True, "sent": sent})


# ---------- signals listing ----------
@app.route("/signals", methods=["GET"])
def get_signals():
    limit = int(request.args.get("limit", 50))
    snap = db.collection("signals").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit).get()
    out = []
    for d in snap:
        rec = d.to_dict()
        rec["id"] = d.id
        out.append(rec)
    return jsonify(out)


# ---------- admin broadcast (protected) ----------
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
    sent = 0
    keys_snap = db.collection("keys").get()
    for kd in keys_snap:
        if is_key_valid_doc(kd):
            notif = {
                "key": kd.id,
                "signal": {"signal": signal, "meta": {"symbol": symbol, "last_price": price}},
                "message": message,
                "timestamp": now_iso()
            }
            db.collection("notifications").add(notif)
            sent += 1
    return jsonify({"sent_to": sent})


# ---------- transactions / deposit / withdraw ----------
@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json or {}
    user = data.get("user", "guest")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    if not all([user, broker, amount]):
        return jsonify({"error": "user/broker/amount required"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "deposit",
        "amount": float(amount),
        "status": "processing",
        "created_at": now_iso()
    }
    ref = db.collection("transactions").add(entry)
    txid = ref[1].id

    try:
        if broker in ["binance", "exness"]:
            # PLACEHOLDER: integrate real API withdraw/transfer via ccxt or provider SDK
            db.collection("transactions").document(txid).update({"status": "completed", "completed_at": now_iso()})
            return jsonify({"tx_id": txid, "status": "completed"})
        elif broker in ["zerodha", "angelone"]:
            redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in"
            db.collection("transactions").document(txid).update({"redirect_url": redirect_url})
            return jsonify({"tx_id": txid, "status": "redirect", "redirect_url": redirect_url})
        else:
            return jsonify({"tx_id": txid, "status": "unsupported"}), 400
    except Exception as e:
        db.collection("transactions").document(txid).update({"status": "failed", "error": str(e)})
        return jsonify({"tx_id": txid, "status": "failed", "error": str(e)}), 500


@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json or {}
    user = data.get("user", "guest")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    if not all([user, broker, amount]):
        return jsonify({"error": "user/broker/amount required"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "withdraw",
        "amount": float(amount),
        "status": "processing",
        "created_at": now_iso()
    }
    ref = db.collection("transactions").add(entry)
    txid = ref[1].id

    try:
        if broker in ["binance", "exness"]:
            db.collection("transactions").document(txid).update({"status": "completed", "completed_at": now_iso()})
            return jsonify({"tx_id": txid, "status": "completed"})
        elif broker in ["zerodha", "angelone"]:
            redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in"
            db.collection("transactions").document(txid).update({"redirect_url": redirect_url})
            return jsonify({"tx_id": txid, "status": "redirect", "redirect_url": redirect_url})
        else:
            return jsonify({"tx_id": txid, "status": "unsupported"}), 400
    except Exception as e:
        db.collection("transactions").document(txid).update({"status": "failed", "error": str(e)})
        return jsonify({"tx_id": txid, "status": "failed", "error": str(e)}), 500


@app.route("/transactions", methods=["GET"])
def list_transactions():
    limit = int(request.args.get("limit", 50))
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


# ---------- cleanup endpoint (admin only) ----------
@app.route("/cleanup", methods=["POST"])
def cleanup():
    auth = request.headers.get("X-Admin-Secret", "")
    if auth != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    deleted = 0
    snap = db.collection("keys").get()
    for d in snap:
        info = d.to_dict() or {}
        exp = info.get("expiry")
        if exp:
            try:
                if datetime.utcnow() > datetime.fromisoformat(exp):
                    db.collection("keys").document(d.id).delete()
                    deleted += 1
            except Exception:
                pass

    cutoff = datetime.utcnow() - timedelta(days=7)
    cancelled = 0
    txsnap = db.collection("transactions").where("status", "==", "processing").get()
    for t in txsnap:
        tdata = t.to_dict() or {}
        created = tdata.get("created_at")
        try:
            if created and datetime.fromisoformat(created) < cutoff:
                db.collection("transactions").document(t.id).update({"status": "cancelled", "updated_at": now_iso()})
                cancelled += 1
        except Exception:
            pass
    return jsonify({"deleted_keys": deleted, "cancelled_tx": cancelled})


# ---------- run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
