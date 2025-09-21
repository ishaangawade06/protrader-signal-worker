from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from kiteconnect import KiteConnect
from smartapi import SmartConnect
import pyotp
import os

# --- Flask app ---
app = Flask(__name__)
CORS(app)

# --- Firebase ---
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccount.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Health Check ---
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
# 🏦 Broker Integrations
# =====================================================

# --- Zerodha Login ---
@app.route("/zerodha/login", methods=["POST"])
def zerodha_login():
    data = request.json
    try:
        kite = KiteConnect(api_key=data["apiKey"])
        # Generate TOTP
        totp = pyotp.TOTP(data["totpSecret"]).now()
        return jsonify({
            "message": "Zerodha login requires browser redirect.",
            "totp": totp,
            "login_url": "https://kite.zerodha.com/"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- AngelOne Login ---
@app.route("/angelone/login", methods=["POST"])
def angelone_login():
    data = request.json
    try:
        obj = SmartConnect(api_key=data["apiKey"])
        totp = pyotp.TOTP(data["totpSecret"]).now()
        session_data = obj.generateSession(data["clientId"], data["password"], totp)
        refreshToken = session_data['data']['refreshToken']
        obj.generateToken(refreshToken)
        return jsonify({"message": "✅ AngelOne login success", "session": session_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# =====================================================
# 🚀 Run
# =====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
