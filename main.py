from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import ccxt
import datetime

# --- Firebase Setup ---
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Flask Setup ---
app = Flask(__name__)
CORS(app)

# --- Mocked broker connections ---
brokers = {
    "binance": ccxt.binance(),
    "exness": None,  # replace with Exness API SDK if available
    "zerodha": None, # placeholder for Zerodha API wrapper
    "angelone": None # placeholder for AngelOne API wrapper
}

# Store balances in Firestore
def get_balance(uid, broker):
    ref = db.collection("users").document(uid).collection("brokers").document(broker)
    snap = ref.get()
    if snap.exists:
        return snap.to_dict().get("balance", "Connect Broker")
    return "Connect Broker"

def update_balance(uid, broker, amount):
    ref = db.collection("users").document(uid).collection("brokers").document(broker)
    ref.set({"balance": float(amount), "updated": datetime.datetime.utcnow().isoformat()}, merge=True)

# --- Routes ---
@app.route("/")
def home():
    return jsonify({"status": "PTH backend running"})

@app.route("/broker/connect", methods=["POST"])
def broker_connect():
    data = request.json
    uid, broker, api_key, secret = data.get("uid"), data.get("broker"), data.get("api_key"), data.get("secret")
    if not uid or broker not in brokers:
        return jsonify({"error": "invalid request"}), 400
    # save broker credentials
    ref = db.collection("users").document(uid).collection("brokers").document(broker)
    ref.set({"api_key": api_key, "secret": secret, "balance": 10000.0})
    return jsonify({"status": "connected"})

@app.route("/balance", methods=["POST"])
def balance():
    data = request.json
    uid, broker = data.get("uid"), data.get("broker")
    bal = get_balance(uid, broker)
    return jsonify({"balance": bal})

@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json
    uid, broker, amount = data.get("uid"), data.get("broker"), float(data.get("amount", 0))
    if broker in ["zerodha", "angelone"]:
        # redirect to official broker page
        return jsonify({"redirect": f"https://{broker}.com/deposit"})
    bal = get_balance(uid, broker)
    try:
        new_bal = float(bal) + amount if bal != "Connect Broker" else amount
        update_balance(uid, broker, new_bal)
        return jsonify({"status": "completed"})
    except:
        return jsonify({"status": "failed"})

@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json
    uid, broker, amount = data.get("uid"), data.get("broker"), float(data.get("amount", 0))
    if broker in ["zerodha", "angelone"]:
        return jsonify({"redirect": f"https://{broker}.com/withdraw"})
    bal = get_balance(uid, broker)
    try:
        new_bal = float(bal) - amount if bal != "Connect Broker" else 0
        update_balance(uid, broker, new_bal)
        return jsonify({"status": "completed"})
    except:
        return jsonify({"status": "failed"})

@app.route("/trade", methods=["POST"])
def trade():
    data = request.json
    uid, broker, symbol, side = data.get("uid"), data.get("broker"), data.get("symbol"), data.get("side")
    amount = float(data.get("amount", 0))
    bal = get_balance(uid, broker)
    if bal == "Connect Broker":
        return jsonify({"status": "failed", "msg": "broker not connected"})
    try:
        if side == "buy":
            new_bal = float(bal) - amount
        else:
            new_bal = float(bal) + amount
        update_balance(uid, broker, new_bal)
        return jsonify({"status": "completed", "new_balance": new_bal})
    except Exception as e:
        return jsonify({"status": "failed", "msg": str(e)})

# --- Run ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
