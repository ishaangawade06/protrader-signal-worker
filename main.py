from flask import Flask, jsonify, request
from firebase_admin import credentials, firestore, initialize_app
import hashlib
from datetime import datetime, timedelta

# Flask App
app = Flask(__name__)

# Firebase Init (use your serviceAccountKey.json in Render)
cred = credentials.Certificate("serviceAccountKey.json")
initialize_app(cred)
db = firestore.client()

# --- Helper: Hash API keys ---
def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

# --- Root Route ---
@app.route("/")
def home():
    return jsonify({"message": "🚀 ProTraderHack Backend Running"})

# --- Sample Signals API ---
@app.route("/api/signals", methods=["GET"])
def get_signals():
    """
    This will later fetch real signals from Firestore,
    but for now we return dummy JSON so frontend works.
    """
    dummy_signals = [
        {"pair": "BTC/USDT", "signal": "BUY", "price": 27450, "time": datetime.utcnow().isoformat()},
        {"pair": "ETH/USDT", "signal": "SELL", "price": 1620, "time": datetime.utcnow().isoformat()},
        {"pair": "BNB/USDT", "signal": "BUY", "price": 215, "time": datetime.utcnow().isoformat()}
    ]
    return jsonify(dummy_signals)

# --- API Key Validation Example (for later use) ---
@app.route("/api/validate", methods=["POST"])
def validate_key():
    data = request.get_json()
    key = data.get("key")

    if not key:
        return jsonify({"error": "API key required"}), 400

    hashed = hash_key(key)
    doc_ref = db.collection("api_keys").document(hashed).get()

    if doc_ref.exists:
        doc = doc_ref.to_dict()
        expiry = doc.get("expiry")
        if expiry and datetime.utcnow() > expiry:
            return jsonify({"valid": False, "reason": "Expired"})
        return jsonify({"valid": True, "role": doc.get("role", "user")})
    else:
        return jsonify({"valid": False, "reason": "Invalid key"})

# --- Run locally (Render will use gunicorn instead) ---
if __name__ == "__main__":
    app.run(debug=True)
