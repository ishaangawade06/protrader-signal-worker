# main.py -- place in protrader-signal-worker/
# Essential endpoints for PTH MVP.
# Requirements: flask flask-cors firebase-admin ccxt requests (optional)
# Set FIREBASE_SERVICE_ACCOUNT env (JSON string) or upload serviceAccount.json

import os, json, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import threading

# optional third-party connectors (install when enabling real brokers)
try:
    import ccxt
except Exception:
    ccxt = None

# Firebase admin
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Config ----------
PORT = int(os.environ.get("PORT", 5000))
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
ADMIN_KEYS = ["vamya", "pthowner16"]   # admin keys (permanent)
DEFAULT_USER_KEYS = {
    "pth7": 7, "key15": 15, "ishaan30": 30, "splkey50": 50, "ishaan": "perm"
}

# ---------- Firebase init ----------
if not firebase_admin._apps:
    if FIREBASE_SERVICE_ACCOUNT:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT))
    elif os.path.exists("serviceAccount.json"):
        cred = credentials.Certificate("serviceAccount.json")
    else:
        raise RuntimeError("Missing Firebase service account: set FIREBASE_SERVICE_ACCOUNT env or add serviceAccount.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- Flask app ----------
app = Flask(__name__)
CORS(app)


def now_iso(): return datetime.utcnow().isoformat()


# ---------- Utilities ----------
def ks_doc(key): return db.collection("keys").document(key)
def user_doc(uid): return db.collection("users").document(uid)
def broker_doc(uid, broker): return user_doc(uid).collection("brokers").document(broker.lower())

def key_remaining_hours(key):
    doc = ks_doc(key).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    expiry = data.get("expiry")
    if not expiry:
        return float('inf')
    try:
        exp_dt = datetime.fromisoformat(expiry)
        delta = exp_dt - datetime.utcnow()
        return max(0, int(delta.total_seconds() // 3600))
    except Exception:
        return None


# ---------- Root & health ----------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"service":"protrader-backend","time":now_iso()})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok","time":now_iso()})


# ---------- Key validation ----------
@app.route("/validate_key", methods=["POST"])
def validate_key():
    data = request.json or {}
    key = data.get("key")
    if not key:
        return jsonify({"valid": False, "reason":"missing_key"}), 400
    # check Firestore keys collection (admin-created keys)
    doc = ks_doc(key).get()
    if doc.exists:
        info = doc.to_dict() or {}
        exp = info.get("expiry")
        if exp:
            try:
                if datetime.utcnow() > datetime.fromisoformat(exp):
                    return jsonify({"valid": False, "reason":"expired"})
            except Exception:
                pass
        return jsonify({"valid": True, "role": info.get("role","user"), "expiry": info.get("expiry")})
    # fallback built-in keys
    if key in DEFAULT_USER_KEYS:
        role = "owner" if DEFAULT_USER_KEYS[key] == "perm" and key == "ishaan" else "user"
        return jsonify({"valid": True, "role": role, "expiry": None})
    return jsonify({"valid": False, "reason":"not_found"})


# ---------- Admin: create / delete keys ----------
# POST /admin/create_key { admin_key, new_key, days (optional), role (user/owner) }
@app.route("/admin/create_key", methods=["POST"])
def create_key():
    data = request.json or {}
    admin_key = data.get("admin_key")
    if admin_key not in ADMIN_KEYS:
        return jsonify({"error":"unauthorized"}), 403
    new_key = data.get("new_key")
    if not new_key:
        return jsonify({"error":"new_key_required"}), 400
    days = data.get("days")  # optional integer
    if days:
        expiry = (datetime.utcnow() + timedelta(days=int(days))).isoformat()
    else:
        expiry = None
    role = data.get("role","user")
    ks_doc(new_key).set({"role":role,"created":now_iso(),"expiry":expiry})
    return jsonify({"created":True,"key":new_key,"expiry":expiry})


# POST /admin/delete_key { admin_key, key }
@app.route("/admin/delete_key", methods=["POST"])
def delete_key():
    data = request.json or {}
    admin_key = data.get("admin_key")
    if admin_key not in ADMIN_KEYS:
        return jsonify({"error":"unauthorized"}),403
    key = data.get("key")
    if not key:
        return jsonify({"error":"key_required"}),400
    ks_doc(key).delete()
    return jsonify({"deleted": key})


# Admin: list users with key+remaining hours
@app.route("/admin/list_users", methods=["GET"])
def admin_list_users():
    admin_key = request.args.get("admin_key")
    if admin_key not in ADMIN_KEYS:
        return jsonify({"error":"unauthorized"}),403
    users = []
    users_snap = db.collection("users").limit(500).stream()
    for u in users_snap:
        udata = u.to_dict() or {}
        users.append({"uid":u.id, "username":udata.get("username"), "keys": udata.get("keys", {})})
    return jsonify(users)


# ---------- Broker connect / disconnect ----------
# POST /broker/connect { uid, broker, api_key, secret, extra... }
@app.route("/broker/connect", methods=["POST"])
def broker_connect():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error":"uid+broker_required"}),400
    store = {}
    for k in ("api_key","secret","client_id","password","access_token","jwt_token","request_token"):
        if k in data:
            store[k] = data[k]
    store["connected"] = True
    store["connected_at"] = now_iso()
    broker_doc(uid, broker).set(store, merge=True)
    # initial balance: fetch real or set placeholder
    broker_doc(uid, broker).set({"balance":"Fetching..."}, merge=True)
    return jsonify({"status":"connected","broker":broker})


@app.route("/broker/disconnect", methods=["POST"])
def broker_disconnect():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error":"uid+broker_required"}),400
    broker_doc(uid, broker).delete()
    return jsonify({"status":"disconnected","broker":broker})


# ---------- Balance endpoint ----------
# POST /balance { uid, broker }
@app.route("/balance", methods=["POST"])
def balance():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    if not uid or not broker:
        return jsonify({"error":"uid+broker_required"}),400
    doc = broker_doc(uid, broker).get()
    if not doc.exists:
        return jsonify({"balance":"Connect Broker"})
    info = doc.to_dict() or {}
    # If balance field exists and numeric, return it; else try to fetch via SDK (TODO)
    bal = info.get("balance")
    if isinstance(bal, (int,float)):
        return jsonify({"balance": float(bal)})
    # Placeholder: try simulated live fetch / or use SDKs here
    # TODO: integrate kiteconnect / smartapi / ccxt here for live balances
    # For now return stored or Connect Broker
    try:
        if bal and isinstance(bal, str) and bal.lower()!="connect broker":
            return jsonify({"balance": bal})
        return jsonify({"balance":"Connect Broker"})
    except Exception:
        return jsonify({"balance":"Connect Broker"})


# ---------- Trade endpoint (simulated) ----------
# POST /trade { uid, broker, symbol, side: buy/sell, amount }
@app.route("/trade", methods=["POST"])
def trade():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    side = (data.get("side") or "").lower()
    symbol = data.get("symbol")
    amount = float(data.get("amount") or 0)
    if not uid or not broker or not side or amount<=0:
        return jsonify({"error":"missing_trade_params"}),400
    doc = broker_doc(uid, broker).get()
    if not doc.exists:
        return jsonify({"error":"broker_not_connected"}),403
    info = doc.to_dict() or {}
    prev_bal = info.get("balance")
    try:
        prev_n = float(prev_bal) if isinstance(prev_bal,(int,float,str)) and str(prev_bal).replace(".","",1).isdigit() else 0.0
    except:
        prev_n = 0.0
    # Simulate market buy subtracting amount; sell adds amount (placeholder logic)
    if side == "buy":
        new_bal = prev_n - amount
    else:
        new_bal = prev_n + amount
    if new_bal < 0:
        return jsonify({"status":"failed", "reason":"insufficient_balance"}),400
    broker_doc(uid, broker).update({"balance": new_bal, "last_trade": now_iso()})
    # Save transaction record
    db.collection("transactions").add({
        "uid": uid, "broker": broker, "symbol": symbol, "side": side, "amount": amount,
        "status": "completed", "time": now_iso()
    })
    return jsonify({"status":"ok","new_balance":new_bal})


# ---------- Deposit / Withdraw ----------
# deposit: POST /deposit { uid, broker, amount }
@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    amount = float(data.get("amount") or 0)
    if not uid or not broker or amount<=0:
        return jsonify({"error":"invalid_params"}),400
    # For Zerodha & AngelOne -> redirect to official pages (recommended)
    if broker in ("zerodha","angelone"):
        url = "https://kite.zerodha.com/funds" if broker=="zerodha" else "https://trade.angelone.in"
        db.collection("transactions").add({"uid":uid,"broker":broker,"type":"deposit","amount":amount,"status":"redirect","time":now_iso(),"redirect":url})
        return jsonify({"status":"redirect","redirect_url":url})
    # For Binance/Exness -> simulate credit
    doc = broker_doc(uid, broker).get()
    if not doc.exists:
        return jsonify({"error":"broker_not_connected"}),403
    info = doc.to_dict() or {}
    prev = info.get("balance") or 0.0
    try:
        prev_n = float(prev)
    except:
        prev_n = 0.0
    new_bal = prev_n + amount
    broker_doc(uid, broker).update({"balance": new_bal, "last_deposit": now_iso()})
    db.collection("transactions").add({"uid":uid,"broker":broker,"type":"deposit","amount":amount,"status":"completed","time":now_iso()})
    return jsonify({"status":"completed","new_balance":new_bal})


# withdraw: POST /withdraw { uid, broker, amount }
@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json or {}
    uid = data.get("uid")
    broker = (data.get("broker") or "").lower()
    amount = float(data.get("amount") or 0)
    if not uid or not broker or amount<=0:
        return jsonify({"error":"invalid_params"}),400
    if broker in ("zerodha","angelone"):
        url = "https://kite.zerodha.com/funds" if broker=="zerodha" else "https://trade.angelone.in"
        db.collection("transactions").add({"uid":uid,"broker":broker,"type":"withdraw","amount":amount,"status":"redirect","time":now_iso(),"redirect":url})
        return jsonify({"status":"redirect","redirect_url":url})
    doc = broker_doc(uid, broker).get()
    if not doc.exists:
        return jsonify({"error":"broker_not_connected"}),403
    info = doc.to_dict() or {}
    prev = info.get("balance") or 0.0
    try:
        prev_n = float(prev)
    except:
        prev_n = 0.0
    if prev_n < amount:
        return jsonify({"error":"insufficient_balance"}),400
    new_bal = prev_n - amount
    broker_doc(uid, broker).update({"balance": new_bal, "last_withdraw": now_iso()})
    db.collection("transactions").add({"uid":uid,"broker":broker,"type":"withdraw","amount":amount,"status":"completed","time":now_iso()})
    return jsonify({"status":"completed","new_balance":new_bal})


# ---------- Signals (store + notify placeholder) ----------
# POST /publish_signal { symbol, signal, meta, broadcast=true }
@app.route("/publish_signal", methods=["POST"])
def publish_signal():
    data = request.json or {}
    symbol = data.get("symbol")
    signal = data.get("signal","INFO")
    meta = data.get("meta",{})
    entry = {"symbol":symbol,"signal":signal,"meta":meta,"timestamp":now_iso()}
    db.collection("signals").add(entry)
    # Optionally add to notifications collection for each key holder
    if data.get("broadcast",True):
        keys = db.collection("keys").stream()
        for k in keys:
            info = k.to_dict() or {}
            expiry = info.get("expiry")
            valid = True
            if expiry:
                try:
                    valid = datetime.utcnow() <= datetime.fromisoformat(expiry)
                except:
                    valid = True
            if valid:
                db.collection("notifications").add({"key":k.id,"message":f"{signal} {symbol}","signal":entry,"timestamp":now_iso()})
    return jsonify({"ok":True})


# ---------- Notifications fetching for user by key (optional) ----------
# GET /notifications?key=...
@app.route("/notifications", methods=["GET"])
def notifications():
    key = request.args.get("key")
    if not key:
        return jsonify([]) 
    snap = db.collection("notifications").where("key","==",key).order_by("timestamp",direction=firestore.Query.DESCENDING).limit(200).stream()
    out = [s.to_dict() for s in snap]
    return jsonify(out)


# ---------- Background maintenance: clean expired keys daily ----------
def cleanup_loop():
    while True:
        try:
            print("[maintenance] scanning expired keys...")
            ks = db.collection("keys").stream()
            for k in ks:
                info = k.to_dict() or {}
                exp = info.get("expiry")
                if exp:
                    try:
                        if datetime.utcnow() > datetime.fromisoformat(exp):
                            db.collection("keys").document(k.id).delete()
                            print("[maintenance] deleted expired key", k.id)
                    except:
                        pass
        except Exception as e:
            print("maintenance error:", e)
        time.sleep(24*3600)

threading.Thread(target=cleanup_loop, daemon=True).start()


# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
