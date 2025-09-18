# main.py
import os
import json
import hashlib
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from firebase_admin import credentials, firestore, initialize_app

# Flask app
app = Flask(__name__)

# CORS - allow /api/* (for quick testing we allow all origins; change to your frontend URL before production)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# Firebase init:
# Prefer SERVICE_ACCOUNT_JSON env var (Render). If missing, fallback to local serviceAccountKey.json file.
sa_json = os.environ.get("SERVICE_ACCOUNT_JSON")
if sa_json:
    sa_dict = json.loads(sa_json)
    cred = credentials.Certificate(sa_dict)
else:
    # fallback (use only for local dev if you have the JSON in repo/workdir)
    cred_path = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")
    cred = credentials.Certificate(cred_path)

initialize_app(cred)
db = firestore.client()

# helper
def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

@app.route("/")
def home():
    return jsonify({"message": "🚀 ProTraderHack Backend Running"})

@app.route("/api/signals", methods=["GET"])
def get_signals():
    # Dummy signals for frontend testing - later replace with Firestore fetch
    dummy_signals = [
        {
            "id": "s1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "27450",
            "target": "28000",
            "stoploss": "27000",
            "timeframe": "1h",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        },
        {
            "id": "s2",
            "symbol": "ETHUSDT",
            "side": "SELL",
            "price": "1620",
            "target": "1500",
            "stoploss": "1700",
            "timeframe": "1h",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    ]
    return jsonify(dummy_signals)

@app.route("/api/validate", methods=["POST"])
def validate_key():
    data = request.get_json() or {}
    key = data.get("key")
    if not key:
        return jsonify({"error": "API key required"}), 400

    hashed = hash_key(key)
    doc = db.collection("api_keys").document(hashed).get()
    if doc.exists:
        docd = doc.to_dict()
        expiry = docd.get("expiry")
        # expiry handling depends on how you store it; this is a safe check placeholder
        if expiry:
            try:
                exp_dt = datetime.fromisoformat(expiry)
                if datetime.utcnow() > exp_dt:
                    return jsonify({"valid": False, "reason": "Expired"})
            except Exception:
                pass
        return jsonify({"valid": True, "role": docd.get("role", "user")})
    return jsonify({"valid": False, "reason": "Invalid key"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
