# main.py (protrader-signal-worker)
# Backend with signal publish -> FCM notifications to users who have symbol in watchlist and a valid key.
import os, json, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading

# Firebase admin
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# ---------- Config ----------
PORT = int(os.environ.get("PORT", 5000))
FIREBASE_SERVICE = os.environ.get("FIREBASE_SERVICE_ACCOUNT")  # set in Render env (JSON string)
ADMIN_KEYS = ["vamya", "pthowner16"]
DEFAULT_USER_KEYS = {"pth7":7,"key15":15,"ishaan30":30,"splkey50":50,"ishaan":"perm"}

# ---------- Firebase init ----------
if not firebase_admin._apps:
    if FIREBASE_SERVICE:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE))
    elif os.path.exists("serviceAccount.json"):
        cred = credentials.Certificate("serviceAccount.json")
    else:
        raise RuntimeError("Provide FIREBASE_SERVICE_ACCOUNT env or serviceAccount.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- Flask ----------
app = Flask(__name__)
CORS(app)

def now_iso(): return datetime.utcnow().isoformat()

# ---------- helpers ----------
def ks_doc(key): return db.collection("keys").document(key)
def user_doc(uid): return db.collection("users").document(uid)
def user_watchlist_ref(uid): return user_doc(uid).collection("meta").document("watchlist")
def user_fcm_ref(uid): return user_doc(uid).collection("meta").document("fcm")

def key_is_valid_for_user(uid):
    doc = user_doc(uid).get()
    if not doc.exists:
        return False
    info = doc.to_dict() or {}
    key = info.get("key")
    key_expiry = info.get("key_expiry")
    # If user uses admin-managed keys in keys collection, check existence+expiry there
    if key:
        # if user.key_expiry stored as ISO
        if key_expiry:
            try:
                if datetime.utcnow() > datetime.fromisoformat(key_expiry):
                    return False
            except:
                pass
        return True
    return False

# ---------- routes ----------
@app.route("/")
def root():
    return {"status":"protrader-backend","time":now_iso()}

# publish a signal (call this from your signal worker)
# POST /publish_signal { symbol, signal, title, body, meta }
@app.route("/publish_signal", methods=["POST"])
def publish_signal():
    req = request.json or {}
    symbol = (req.get("symbol") or "").upper()
    signal = req.get("signal","INFO")
    title = req.get("title") or f"PTH Signal: {symbol}"
    body = req.get("body") or f"{signal} {symbol}"
    meta = req.get("meta", {})

    if not symbol:
        return {"error":"symbol required"},400

    # store signal record
    sig_doc = {"symbol":symbol,"signal":signal,"title":title,"body":body,"meta":meta,"timestamp":now_iso()}
    db.collection("signals").add(sig_doc)

    # Find users whose watchlist contains symbol
    users = db.collection("users").stream()
    tokens_to_notify = []  # list of (token, uid)
    for u in users:
        uid = u.id
        # check user key validity
        if not key_is_valid_for_user(uid):
            continue
        # check watchlist document
        try:
            wdoc = user_watchlist_ref(uid).get()
            if not wdoc.exists:
                continue
            watch = wdoc.to_dict().get("items", [])
            # accept matching if any watchlist entry equals symbol (case-insensitive)
            if symbol.upper() not in [s.upper() for s in watch]:
                continue
            # get fcm token
            fdoc = user_fcm_ref(uid).get()
            if not fdoc.exists:
                continue
            token = fdoc.to_dict().get("token")
            if token:
                tokens_to_notify.append((token, uid))
        except Exception as e:
            print("watchlist check error", uid, e)
            continue

    # send messages (batch messages with messaging.send_all)
    if tokens_to_notify:
        messages = []
        for token, uid in tokens_to_notify:
            msg = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=token,
                android=messaging.AndroidConfig(priority="high"),
                apns=messaging.APNSConfig(headers={"apns-priority":"10"})
            )
            messages.append(msg)
        # try send_all (max 500)
        try:
            resp = messaging.send_all(messages)
            print("FCM send_all success:", resp.success_count, "failed:", resp.failure_count)
        except Exception as e:
            print("FCM send_all error:", e)

    return {"ok":True, "notified": len(tokens_to_notify)}

# Endpoint to let frontend save FCM token to the user's doc
# POST /save_fcm_token { uid, token }
@app.route("/save_fcm_token", methods=["POST"])
def save_fcm_token():
    data = request.json or {}
    uid = data.get("uid")
    token = data.get("token")
    if not uid or not token:
        return {"error":"uid+token required"},400
    user_fcm_ref(uid).set({"token": token, "saved_at": now_iso()})
    return {"ok":True}

# Endpoint to update watchlist for a user
# POST /watchlist { uid, items: [ "BTCUSDT", "AAPL" ] }
@app.route("/watchlist", methods=["POST"])
def update_watchlist():
    data = request.json or {}
    uid = data.get("uid")
    items = data.get("items", [])
    if not uid:
        return {"error":"uid required"},400
    user_watchlist_ref(uid).set({"items": items, "updated": now_iso()})
    return {"ok":True}

# health
@app.route("/health", methods=["GET"])
def health():
    return {"status":"ok"}

# run
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
