import os
import json
import requests
import ccxt
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)
CORS(app)

# ===== FIREBASE INIT =====
cred = credentials.Certificate(json.loads(os.environ.get("FIREBASE_SERVICE_ACCOUNT")))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ===== ANGELONE SYMBOL MAP =====
symbol_token_map = {}

def load_scrip_master():
    global symbol_token_map
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        resp = requests.get(url, timeout=15)
        data = resp.json()
        temp_map = {}
        for s in data:
            key = f"{s['symbol']}-{s['exch_seg']}"
            temp_map[key] = s['token']
        symbol_token_map = temp_map
        print(f"✅ Loaded {len(symbol_token_map)} AngelOne symbols")
    except Exception as e:
        print("❌ Failed loading scrip master:", e)

load_scrip_master()

scheduler = BackgroundScheduler()
scheduler.add_job(load_scrip_master, 'interval', days=1)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ====== ROUTES ======

@app.route("/")
def root():
    return jsonify({"message": "PTH Backend running"})

# --- Binance/Exness balance
@app.route("/binance/balance", methods=["POST"])
def binance_balance():
    data = request.json
    try:
        exchange = getattr(ccxt, data.get("exchange", "binance"))({
            "apiKey": data["apiKey"],
            "secret": data["secretKey"],
            "enableRateLimit": True
        })
        bal = exchange.fetch_balance()
        return jsonify(bal)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- Binance/Exness trade
@app.route("/binance/trade", methods=["POST"])
def binance_trade():
    data = request.json
    try:
        exchange = getattr(ccxt, data.get("exchange", "binance"))({
            "apiKey": data["apiKey"],
            "secret": data["secretKey"],
            "enableRateLimit": True
        })
        order = exchange.create_market_order(
            symbol=data["symbol"],
            side=data["side"],
            amount=float(data["quantity"])
        )
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- Binance/Exness deposit address
@app.route("/binance/depositAddress", methods=["POST"])
def binance_deposit_address():
    data = request.json
    try:
        exchange = getattr(ccxt, data.get("exchange", "binance"))({
            "apiKey": data["apiKey"],
            "secret": data["secretKey"],
            "enableRateLimit": True
        })
        addr = exchange.fetchDepositAddress(data["currency"])
        return jsonify(addr)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- Binance/Exness withdraw
@app.route("/binance/withdraw", methods=["POST"])
def binance_withdraw():
    data = request.json
    try:
        exchange = getattr(ccxt, data.get("exchange", "binance"))({
            "apiKey": data["apiKey"],
            "secret": data["secretKey"],
            "enableRateLimit": True
        })
        result = exchange.withdraw(
            code=data["currency"],
            amount=float(data["amount"]),
            address=data["address"]
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- Zerodha placeholders
@app.route("/zerodha/deposit", methods=["POST"])
def zerodha_deposit():
    return jsonify({"message": "Deposit/Withdraw must be done via Zerodha app."})

@app.route("/zerodha/withdraw", methods=["POST"])
def zerodha_withdraw():
    return jsonify({"message": "Deposit/Withdraw must be done via Zerodha app."})

# --- AngelOne placeholders
@app.route("/angelone/deposit", methods=["POST"])
def angelone_deposit():
    return jsonify({"message": "Deposit/Withdraw must be done via AngelOne app."})

@app.route("/angelone/withdraw", methods=["POST"])
def angelone_withdraw():
    return jsonify({"message": "Deposit/Withdraw must be done via AngelOne app."})

# --- AngelOne trade
@app.route("/angelone/trade", methods=["POST"])
def angelone_trade():
    data = request.json
    if data["symbol"] not in symbol_token_map:
        return jsonify({"error": "Symbol not found"}), 400
    return jsonify({"message": f"Mock trade for {data['symbol']} {data['side']} {data['quantity']}"})

# --- AngelOne manual refresh
@app.route("/angelone/refreshSymbols", methods=["POST"])
def angel_refresh():
    try:
        load_scrip_master()
        return jsonify({"message": f"✅ Reloaded {len(symbol_token_map)} AngelOne symbols"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
