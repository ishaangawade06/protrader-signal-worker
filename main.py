# main.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore, messaging
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Firebase init
cred_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
if cred_json:
    import json
    cred = credentials.Certificate(json.loads(cred_json))
else:
    cred = credentials.Certificate("serviceAccount.json")

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- Root ---
@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "PTH Backend"})


# --- Save signal ---
@app.route("/add-signal", methods=["POST"])
def add_signal():
    data = request.json
    if not data or "symbol" not in data:
        return jsonify({"error": "invalid data"}), 400

    data["timestamp"] = datetime.utcnow().isoformat()

    # Save in Firestore
    ref = db.collection("signals").document()
    ref.set(data)

    # Send FCM notification to all users with tokens
    try:
        tokens = []
        users = db.collection("users").stream()
        for u in users:
            tok = u.to_dict().get("fcmToken")
            if tok:
                tokens.append(tok)

        if tokens:
            message = messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(
                    title=f"New {data['signal']} Signal",
                    body=f"{data['symbol']} @ {data.get('last_price','')}"
                ),
                data={"symbol": data["symbol"], "signal": data["signal"]}
            )
            response = messaging.send_multicast(message)
            print(f"✅ Sent notification to {response.success_count}/{len(tokens)} users")
    except Exception as e:
        print("⚠️ Notification error:", e)

    return jsonify({"success": True, "id": ref.id})


# --- List signals ---
@app.route("/signals", methods=["GET"])
def get_signals():
    snap = db.collection("signals").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(30).stream()
    signals = [s.to_dict() | {"id": s.id} for s in snap]
    return jsonify(signals)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
