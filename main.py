import os
import json
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- Firestore Init ----------------
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

# ---------------- Helpers ----------------
def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()

def save_key_to_db(key: str, role: str = "user", days: int = None, db=db):
    """Save API key to Firestore"""
    if not db:
        print("⚠️ No Firestore DB connected.")
        return
    expiry = None
    if days:
        expiry = datetime.utcnow() + timedelta(days=days)
    doc_ref = db.collection("keys").document(hash_key(key))
    doc_ref.set({
        "role": role,
        "created": datetime.utcnow().isoformat(),
        "expiry": expiry.isoformat() if expiry else None
    })
    print(f"✅ Key saved: {key} ({role}, expiry={expiry})")

def validate_key(key: str, db=db):
    """Validate API key against Firestore"""
    if not db:
        return {"valid": False}
    try:
        doc = db.collection("keys").document(hash_key(key)).get()
        if not doc.exists:
            return {"valid": False}
        data = doc.to_dict()
        expiry = data.get("expiry")
        if expiry:
            exp = datetime.fromisoformat(expiry)
            if datetime.utcnow() > exp:
                return {"valid": False, "expired": True}
        return {
            "valid": True,
            "role": data.get("role", "user"),
            "expiry": expiry
        }
    except Exception as e:
        print("validate_key error:", e)
        return {"valid": False}

# ---------------- Flask API ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"message": "🚀 ProTrader Signal Worker is running"})

@app.route("/get-signal", methods=["POST"])
def get_signal():
    """
    Example endpoint to return trading signals.
    Requires JSON body: { "api_key": "xxxx" }
    """
    data = request.json
    api_key = data.get("api_key")

    validation = validate_key(api_key)
    if not validation.get("valid"):
        return jsonify({"error": "Invalid or expired key"}), 403

    # Dummy signal generator (replace with real trading logic)
    signal = {
        "pair": "BTC/USDT",
        "action": "BUY",
        "confidence": "92%",
        "timestamp": datetime.utcnow().isoformat()
    }

    return jsonify({"signal": signal, "role": validation.get("role")})

@app.route("/admin/create-key", methods=["POST"])
def create_key():
    """
    Only owner can create new keys.
    Requires JSON body: { "api_key": "owner-key", "new_key": "xxx", "days": 30 }
    """
    data = request.json
    api_key = data.get("api_key")
    new_key = data.get("new_key")
    days = data.get("days", None)

    validation = validate_key(api_key)
    if not (validation.get("valid") and validation.get("role") == "owner"):
        return jsonify({"error": "Unauthorized"}), 403

    save_key_to_db(new_key, "user", days)
    return jsonify({"message": "✅ New key created", "key": new_key})

# ---------------- Run ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from backend.auth import validate_key  # your earlier auth system

app = FastAPI()

# Allow frontend calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/signal")
def get_signal(api_key: str):
    validation = validate_key(api_key)
    if not validation.get("valid"):
        return {"error": "Invalid or expired key"}

    # Example signal
    signal = {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "confidence": "93%",
        "timestamp": "2025-09-17 14:32 UTC"
    }
    return {"signal": signal}
