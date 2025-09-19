import os
import json
import hashlib
import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firebase Setup ----------
service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------- Flask App ----------
app = Flask(__name__)
CORS(app)   # enable CORS so frontend (GitHub Pages) can call backend

# ---------- Utility ----------
def hash_key(api_key: str) -> str:
    """Securely hash API key using SHA256"""
    return hashlib.sha256(api_key.encode()).hexdigest()

# ---------- Routes ----------

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"message": "PTH Backend is live ✅"})

@app.route("/validate", methods=["POST"])
def validate():
    """Validate API key and expiry"""
    data = request.json
    api_key = data.get("api_key")

    if not api_key:
        return jsonify({"error": "API key missing"}), 400

    hashed = hash_key(api_key)
    doc_ref = db.collection("api_keys").document(hashed)
    doc = doc_ref.get()

    if not doc.exists:
        return jsonify({"error": "Invalid API key"}), 403

    record = doc.to_dict()
    expiry = record.get("expiry")

    if expiry and datetime.datetime.utcnow() > expiry:
        return jsonify({"error": "API key expired"}), 403

    return jsonify({"success": True, "role": record.get("role", "user")})

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
