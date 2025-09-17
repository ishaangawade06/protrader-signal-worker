import os
import json
import hashlib
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

# ------------------- INIT APP -------------------
app = Flask(__name__)

db = None
try:
    if not firebase_admin._apps:
        service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firestore connected successfully")
except Exception as e:
    print("❌ Firestore init failed:", e)


# ------------------- HELPERS -------------------
def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


# ------------------- SAVE API KEY -------------------
def save_key_to_db(key: str, role: str = "user", days: int = None):
    if not db:
        print("⚠️ No Firestore DB connected.")
        return False

    expiry = None
    if days:
        expiry = datetime.utcnow() + timedelta(days=days)

    doc_ref = db.collection("keys").document(hash_key(key))
    doc_ref.set({
        "role": role,
        "created": datetime.utcnow().isoformat(),
        "expiry": expiry.isoformat() if expiry else None
    })
    return True


# ------------------- VALIDATE API KEY -------------------
def validate_key(key: str):
    if not db:
        return {"valid": False, "error": "No database"}

    try:
        doc = db.collection("keys").document(hash_key(key)).get()
        if not doc.exists:
            return {"valid": False, "error": "Key not found"}

        data = doc.to_dict()
        expiry = data.get("expiry")

        if expiry:
            exp = datetime.fromisoformat(expiry)
            if datetime.utcnow() > exp:
                return {"valid": False, "error": "Key expired"}

        return {
            "valid": True,
            "role": data.get("role", "user"),
            "expiry": expiry
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ------------------- ROUTES -------------------
@app.route("/")
def home():
    return jsonify({"status": "✅ ProTraderHack backend running"})


@app.route("/validate-key", methods=["POST"])
def validate_key_route():
    data = request.json
    key = data.get("api_key")
    if not key:
        return jsonify({"valid": False, "error": "Missing key"}), 400

    result = validate_key(key)
    return jsonify(result)


@app.route("/signal", methods=["POST"])
def get_signal():
    """
    Example protected endpoint
    Requires valid API key
    """
    data = request.json
    key = data.get("api_key")

    validation = validate_key(key)
    if not validation["valid"]:
        return jsonify(validation), 403

    # Dummy signal logic (replace with real trading logic later)
    signal = {
        "pair": "BTC/USDT",
        "action": "BUY",
        "confidence": "87%",
        "timestamp": datetime.utcnow().isoformat()
    }

    return jsonify({"valid": True, "signal": signal})


# ------------------- MAIN -------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
