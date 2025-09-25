# main.py
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore, auth as fb_auth

# import our brokers module
from brokers import (
    get_balance_for_user_broker,
    place_order_for_user_broker,
    zerodha_create_session,
    angel_create_session,
)

# ---------- CONFIG ----------
PORT = int(os.environ.get("PORT", 5000))
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")  # JSON string
ADMIN_KEYS = ["vamya", "pthowner16"]

# ---------- Firebase init ----------
if not firebase_admin._apps:
    if FIREBASE_SERVICE_ACCOUNT:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT))
    elif os.path.exists("serviceAccount.json"):
        cred = credentials.Certificate("serviceAccount.json")
    else:
        raise RuntimeError("Missing Firebase service account (set FIREBASE_SERVICE_ACCOUNT env or upload file).")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------- Flask app ----------
app = Flask(__name__)
CORS(app)

# ---------- Utils ----------
def user_broker_doc(uid: str, broker: str):
    return db.collection("users").document(uid).collection("brokers").document(broker.lower())

def read_broker_creds(uid: str, broker: str) -> dict:
    doc = user_broker_doc(uid, broker).get()
    if not doc.exists:
        return {}
    return doc.to_dict()

def write_broker_creds(uid: str, broker: str, payload: dict):
    user_broker_doc(uid, broker).set(payload, merge=True)

def update_balance_in_store(uid: str, broker: str, balance_info: dict):
    user_broker_doc(uid, broker).update({
        "balance": balance_info.get("balance"),
        "last_update": datetime.utcnow().isoformat()
    })

# ---------- Routes ----------
@app.route("/")
def index():
    return jsonify({"status": "PTH backend running", "time": datetime.utcnow().isoformat()})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# Connect broker (store credentials)
# POST body: { "uid": "...", "broker": "zerodha", "api_key": "...", "secret": "...", ... }
@app.route("/broker/connect", methods=["POST"])
def connect_broker():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error": "uid and broker required"}), 400

    # Save basic fields
    payload = {}
    for k in ("api_key", "secret", "client_id", "password", "totp_secret", "access_token", "jwt_token"):
        if k in data:
            payload[k] = data[k]
    payload["connected"] = True
    payload["connected_at"] = datetime.utcnow().isoformat()
    write_broker_creds(uid, broker, payload)

    # If Zerodha and request_token present, exchange session
    if broker == "zerodha" and data.get("request_token") and data.get("api_key"):
        try:
            sess = zerodha_create_session(data["api_key"], data["request_token"], data.get("secret"))
            write_broker_creds(uid, broker, {"access_token": sess.get("access_token")})
        except Exception as e:
            return jsonify({"error": f"zerodha session error: {str(e)}"}), 500

    # If AngelOne and client_id/password provided, create session if possible
    if broker == "angelone" and data.get("api_key") and data.get("client_id") and data.get("password"):
        try:
            sess = angel_create_session(data["api_key"], data["client_id"], data["password"], data.get("totp_secret"))
            # session return shape varies; store raw
            write_broker_creds(uid, broker, {"jwt_token": sess.get("session")})
        except Exception as e:
            return jsonify({"error": f"angel session error: {str(e)}"}), 500

    return jsonify({"status": "connected", "broker": broker})

# Disconnect broker
@app.route("/broker/disconnect", methods=["POST"])
def disconnect_broker():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error": "uid and broker required"}), 400
    user_broker_doc(uid, broker).delete()
    return jsonify({"status": "disconnected", "broker": broker})

# Get balance: returns "Connect Broker" if not connected
# POST { uid, broker }
@app.route("/balance", methods=["POST"])
def balance_route():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error": "uid and broker required"}), 400

    creds = read_broker_creds(uid, broker)
    if not creds or not creds.get("connected"):
        return jsonify({"balance": "Connect Broker"})

    try:
        bal = get_balance_for_user_broker(broker, creds)
    except Exception as e:
        return jsonify({"error": f"balance fetch failed: {str(e)}"}), 500

    # store latest numeric balance if present
    if isinstance(bal, dict) and "balance" in bal and isinstance(bal["balance"], (int, float)):
        update_balance_in_store(uid, broker, bal)
    return jsonify(bal)

# Place trade: POST { uid, broker, action: buy/sell, order_payload }
@app.route("/trade", methods=["POST"])
def trade_route():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    action = data.get("action")
    order_payload = data.get("order_payload", {})

    if not uid or not broker or not action:
        return jsonify({"error": "uid, broker, action required"}), 400

    creds = read_broker_creds(uid, broker)
    if not creds or not creds.get("connected"):
        return jsonify({"error": "Broker not connected"}), 403

    try:
        res = place_order_for_user_broker(broker, creds, order_payload)
    except Exception as e:
        return jsonify({"error": f"order failed: {str(e)}"}), 500

    # After order, refresh balance
    try:
        bal = get_balance_for_user_broker(broker, creds)
        if isinstance(bal, dict) and "balance" in bal and isinstance(bal["balance"], (int, float)):
            update_balance_in_store(uid, broker, bal)
    except Exception as e:
        # don't fail trade because balance refresh failed; return trade result with warning
        res = {"result": res, "balance_refresh_error": str(e)}

    return jsonify({"trade_result": res, "balance": bal})

# Deposit / Withdraw endpoints — after these actions we refresh balance
@app.route("/deposit", methods=["POST"])
def deposit_route():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    if not uid or not broker or not amount:
        return jsonify({"error": "uid, broker, amount required"}), 400

    # For Zerodha/AngelOne redirect to their pages (recommended)
    if broker in ("zerodha", "angelone"):
        redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in/funds"
        # create a transaction doc (optional)
        db.collection("transactions").add({
            "uid": uid, "broker": broker, "amount": float(amount),
            "type": "deposit", "status": "redirect", "created_at": datetime.utcnow().isoformat(), "redirect_url": redirect_url
        })
        return jsonify({"status": "redirect", "redirect_url": redirect_url})

    # For Binance/Exness — you could call CCXT to transfer/credit — here we simulate and refresh balance
    db.collection("transactions").add({
        "uid": uid, "broker": broker, "amount": float(amount),
        "type": "deposit", "status": "processing", "created_at": datetime.utcnow().isoformat()
    })
    # refresh balance
    creds = read_broker_creds(uid, broker)
    if creds:
        try:
            bal = get_balance_for_user_broker(broker, creds)
            if isinstance(bal, dict) and "balance" in bal and isinstance(bal["balance"], (int, float)):
                update_balance_in_store(uid, broker, bal)
        except Exception:
            pass
    return jsonify({"status": "processing"})

@app.route("/withdraw", methods=["POST"])
def withdraw_route():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    amount = data.get("amount")
    if not uid or not broker or not amount:
        return jsonify({"error": "uid, broker, amount required"}), 400

    if broker in ("zerodha", "angelone"):
        redirect_url = "https://kite.zerodha.com/funds" if broker == "zerodha" else "https://trade.angelone.in/funds"
        db.collection("transactions").add({
            "uid": uid, "broker": broker, "amount": float(amount),
            "type": "withdraw", "status": "redirect", "created_at": datetime.utcnow().isoformat(), "redirect_url": redirect_url
        })
        return jsonify({"status": "redirect", "redirect_url": redirect_url})

    db.collection("transactions").add({
        "uid": uid, "broker": broker, "amount": float(amount),
        "type": "withdraw", "status": "processing", "created_at": datetime.utcnow().isoformat()
    })
    # refresh balance
    creds = read_broker_creds(uid, broker)
    if creds:
        try:
            bal = get_balance_for_user_broker(broker, creds)
            if isinstance(bal, dict) and "balance" in bal and isinstance(bal["balance"], (int, float)):
                update_balance_in_store(uid, broker, bal)
        except Exception:
            pass
    return jsonify({"status": "processing"})

# Admin: create key
@app.route("/admin/keys", methods=["POST"])
def admin_create_key():
    data = request.json or {}
    admin_key = data.get("admin_key")
    if admin_key not in ADMIN_KEYS:
        return jsonify({"error": "Unauthorized"}), 403
    new_key = data.get("new_key")
    role = data.get("role", "user")
    expiry = data.get("expiry")  # optional iso string
    db.collection("keys").document(new_key).set({"role": role, "expiry": expiry, "created_at": datetime.utcnow().isoformat()})
    return jsonify({"created": True, "key": new_key})

# Run app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
