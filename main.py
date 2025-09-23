from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import requests

app = Flask(__name__)
CORS(app)

# --- Firebase Init ---
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccount.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Admin Secret ---
PTH_ADMIN_SECRET = "supersecret123"

@app.route("/")
def home():
    return jsonify({"status": "ok", "service": "ProTraderHack Backend"})

# =====================================================
# 🔑 Key Validation
# =====================================================
@app.route("/validate_key", methods=["POST"])
def validate_key():
    data = request.json
    key = data.get("key")
    if not key:
        return jsonify({"error": "No key provided"}), 400

    doc = db.collection("keys").document(key).get()
    if not doc.exists:
        return jsonify({"valid": False, "reason": "Key not found"})

    info = doc.to_dict()
    expiry = info.get("expiry")

    if expiry and datetime.utcnow() > datetime.fromisoformat(expiry):
        return jsonify({"valid": False, "reason": "Expired"})

    return jsonify({"valid": True, "role": info.get("role", "user")})

# =====================================================
# 💳 Deposit / Withdraw (Broker Integrated)
# =====================================================
@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json
    user = data.get("user")
    broker = data.get("broker")
    amount = data.get("amount", 0)

    if not all([user, broker, amount]):
        return jsonify({"error": "Missing fields"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "deposit",
        "amount": amount,
        "status": "processing",
        "timestamp": datetime.utcnow().isoformat()
    }

    # Handle broker cases
    if broker.lower() in ["zerodha", "angelone"]:
        entry["redirect_url"] = f"https://{broker}.com/deposit"
    elif broker.lower() == "binance":
        # Example Binance API call (pseudo)
        entry["status"] = "completed"
    elif broker.lower() == "exness":
        # Example Exness API call (pseudo)
        entry["status"] = "completed"

    ref = db.collection("transactions").add(entry)
    entry["id"] = ref[1].id
    return jsonify(entry)

@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json
    user = data.get("user")
    broker = data.get("broker")
    amount = data.get("amount", 0)

    if not all([user, broker, amount]):
        return jsonify({"error": "Missing fields"}), 400

    entry = {
        "user": user,
        "broker": broker,
        "type": "withdraw",
        "amount": amount,
        "status": "processing",
        "timestamp": datetime.utcnow().isoformat()
    }

    if broker.lower() in ["zerodha", "angelone"]:
        entry["redirect_url"] = f"https://{broker}.com/withdraw"
    elif broker.lower() == "binance":
        entry["status"] = "completed"
    elif broker.lower() == "exness":
        entry["status"] = "completed"

    ref = db.collection("transactions").add(entry)
    entry["id"] = ref[1].id
    return jsonify(entry)

# =====================================================
# 📜 Transactions
# =====================================================
@app.route("/transactions", methods=["GET"])
def transactions():
    snap = db.collection("transactions").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(50).get()
    results = [doc.to_dict() | {"id": doc.id} for doc in snap]
    return jsonify(results)

@app.route("/transactions/<txid>", methods=["PATCH"])
def update_transaction(txid):
    auth_header = request.headers.get("X-Admin-Secret")
    if auth_header != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    status = data.get("status")
    if status not in ["processing", "completed", "cancelled"]:
        return jsonify({"error": "Invalid status"}), 400

    db.collection("transactions").document(txid).update({"status": status})
    return jsonify({"message": f"Transaction {txid} updated to {status}"})

# =====================================================
# 📢 Broadcast Notification (Admin Only)
# =====================================================
@app.route("/send_notification", methods=["POST"])
def send_notification():
    auth_header = request.headers.get("X-Admin-Secret")
    if auth_header != PTH_ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json or {}
    entry = {
        "message": data.get("message", ""),
        "symbol": data.get("symbol", "GENERIC"),
        "signal": data.get("signal", "INFO"),
        "price": data.get("price", "-"),
        "timestamp": datetime.utcnow().isoformat()
    }
    db.collection("notifications").add(entry)
    return jsonify({"sent_to": "all_valid_users", "entry": entry})

# =====================================================
# 🚀 Run
# =====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
