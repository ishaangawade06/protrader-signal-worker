import os
import json
import requests
import pandas as pd
from flask import Flask, request, jsonify
from datetime import datetime
from signals import hybrid_signal
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ---------------- ENV ----------------
FIREBASE_SERVER = json.loads(os.environ.get("FIREBASE_SERVER", "{}"))
FCM_TOPIC = os.environ.get("FCM_TOPIC", "signals")
ADMIN_KEYS = ["vamya", "pthowner16"]

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return jsonify({"status": "PTH backend is live 🚀"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

# ---------------- AUTH / KEYS ----------------
@app.route("/validate_key", methods=["POST"])
def validate_key():
    data = request.json
    key = data.get("key")
    if key in ["pth7", "key15", "ishaan30", "splkey50", "ishaan"]:
        return jsonify({"valid": True})
    return jsonify({"valid": False})

@app.route("/admin_action", methods=["POST"])
def admin_action():
    data = request.json
    key = data.get("admin_key")
    if key not in ADMIN_KEYS:
        return jsonify({"error": "unauthorized"}), 403
    return jsonify({"status": "ok", "action": data.get("action", "none")})

# ---------------- SIGNAL GENERATION ----------------
@app.route("/generate_signal", methods=["POST"])
def generate_signal():
    try:
        data = request.json
        df = pd.DataFrame(data["ohlcv"])
        signal = hybrid_signal(df)
        notify_users(signal)
        return jsonify(signal)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def notify_users(signal):
    if not FIREBASE_SERVER:
        return
    headers = {
        "Authorization": f"key={FIREBASE_SERVER.get('private_key')}",
        "Content-Type": "application/json",
    }
    body = {
        "to": f"/topics/{FCM_TOPIC}",
        "notification": {
            "title": f"Signal: {signal['signal']}",
            "body": f"{signal['meta']['entry']} | Confidence {signal['confidence']*100:.1f}%",
        },
        "data": signal,
    }
    try:
        requests.post("https://fcm.googleapis.com/fcm/send", headers=headers, json=body)
    except Exception as e:
        print("FCM error:", e)

# ---------------- BROKER INTEGRATION ----------------
@app.route("/connect_broker", methods=["POST"])
def connect_broker():
    data = request.json
    broker = data.get("broker")
    api_key = data.get("api_key")
    secret = data.get("secret")
    return jsonify({"status": "connected", "broker": broker})

@app.route("/balance", methods=["POST"])
def balance():
    data = request.json
    broker = data.get("broker")
    # Fake balances for demo
    balances = {
        "zerodha": 100000,
        "angelone": 75000,
        "binance": 2.54,
        "exness": 1200,
    }
    return jsonify({"broker": broker, "balance": balances.get(broker.lower(), 0)})

@app.route("/order", methods=["POST"])
def order():
    data = request.json
    broker = data.get("broker")
    side = data.get("side")  # BUY / SELL
    symbol = data.get("symbol")
    qty = data.get("qty", 1)
    return jsonify({
        "status": "order placed",
        "broker": broker,
        "side": side,
        "symbol": symbol,
        "qty": qty,
        "time": datetime.utcnow().isoformat()
    })

# ---------------- DEPOSIT / WITHDRAW ----------------
@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json
    broker = data.get("broker")
    amount = data.get("amount")
    if broker.lower() in ["zerodha", "angelone"]:
        return jsonify({"redirect_url": f"https://{broker}.com/deposit"})
    return jsonify({"status": "processing", "broker": broker, "amount": amount})

@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json
    broker = data.get("broker")
    amount = data.get("amount")
    if broker.lower() in ["zerodha", "angelone"]:
        return jsonify({"redirect_url": f"https://{broker}.com/withdraw"})
    return jsonify({"status": "processing", "broker": broker, "amount": amount})

# ---------------- SCRIP MASTER REFRESH ----------------
def refresh_scrip_master():
    print("Refreshing scrip master at", datetime.utcnow())

scheduler = BackgroundScheduler()
scheduler.add_job(refresh_scrip_master, "interval", days=1)
scheduler.start()

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
