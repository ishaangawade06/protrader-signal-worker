from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore, messaging
import datetime

# --- Firebase Setup ---
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Flask Setup ---
app = Flask(__name__)
CORS(app)

# --- Utility Functions ---
def broker_doc(uid, broker):
    return db.collection("users").document(uid).collection("brokers").document(broker)

def get_balance(uid, broker):
    snap = broker_doc(uid, broker).get()
    return snap.to_dict().get("balance", "Connect Broker") if snap.exists else "Connect Broker"

def update_balance(uid, broker, amount):
    broker_doc(uid, broker).set({
        "balance": float(amount),
        "updated": datetime.datetime.utcnow().isoformat()
    }, merge=True)

# --- Routes ---
@app.route("/")
def home():
    return jsonify({"status": "PTH backend running"})

@app.route("/broker/connect", methods=["POST"])
def broker_connect():
    data = request.json
    uid, broker, api_key, secret = data.get("uid"), data.get("broker"), data.get("api_key"), data.get("secret")
    broker_doc(uid, broker).set({"api_key": api_key, "secret": secret, "balance": 10000.0})
    return jsonify({"status": "connected"})

@app.route("/broker/disconnect", methods=["POST"])
def broker_disconnect():
    data = request.json
    uid, broker = data.get("uid"), data.get("broker")
    broker_doc(uid, broker).delete()
    return jsonify({"status": "disconnected"})

@app.route("/balance", methods=["POST"])
def balance():
    data = request.json
    uid, broker = data.get("uid"), data.get("broker")
    return jsonify({"balance": get_balance(uid, broker)})

@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json
    uid, broker, amount = data.get("uid"), data.get("broker"), float(data.get("amount", 0))
    if broker in ["zerodha", "angelone"]:
        return jsonify({"redirect": f"https://{broker}.com/funds"})
    bal = get_balance(uid, broker)
    new_bal = (float(bal) if bal != "Connect Broker" else 0) + amount
    update_balance(uid, broker, new_bal)
    return jsonify({"status": "completed", "new_balance": new_bal})

@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json
    uid, broker, amount = data.get("uid"), data.get("broker"), float(data.get("amount", 0))
    if broker in ["zerodha", "angelone"]:
        return jsonify({"redirect": f"https://{broker}.com/funds"})
    bal = get_balance(uid, broker)
    new_bal = (float(bal) if bal != "Connect Broker" else 0) - amount
    update_balance(uid, broker, new_bal)
    return jsonify({"status": "completed", "new_balance": new_bal})

@app.route("/trade", methods=["POST"])
def trade():
    data = request.json
    uid, broker, side, amount = data.get("uid"), data.get("broker"), data.get("side"), float(data.get("amount", 0))
    bal = get_balance(uid, broker)
    if bal == "Connect Broker": return jsonify({"status": "failed", "msg": "broker not connected"}), 400
    new_bal = float(bal) - amount if side == "buy" else float(bal) + amount
    update_balance(uid, broker, new_bal)
    return jsonify({"status": "completed", "new_balance": new_bal})

# --- Notifications ---
@app.route("/notify", methods=["POST"])
def notify():
    """Send push notification if user has valid key"""
    data = request.json
    uid, title, body = data.get("uid"), data.get("title"), data.get("body")
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists: return {"error":"user not found"},404
    user_data = user_doc.to_dict()
    if not user_data.get("key_valid"): return {"error":"user key invalid"},403
    token = user_data.get("fcm_token")
    if not token: return {"error":"no fcm token"},400
    message = messaging.Message(notification=messaging.Notification(title=title, body=body), token=token)
    messaging.send(message)
    return {"status":"sent"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
