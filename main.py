import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

# Brokers
import ccxt
from kiteconnect import KiteConnect
from smartapi import SmartConnect
import pyotp

# Firebase setup
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app)

# ================== BROKER SESSIONS ==================
binance_sessions = {}
zerodha_sessions = {}
angel_sessions = {}

# ================== BINANCE / EXNESS ==================
@app.route("/binance/link", methods=["POST"])
def binance_link():
    try:
        data = request.json
        uid = data.get("uid")
        api_key = data.get("apiKey")
        secret = data.get("secretKey")
        ex = data.get("exchange", "binance")
        exchange = getattr(ccxt, ex)({
            "apiKey": api_key,
            "secret": secret
        })
        binance_sessions[uid] = exchange
        return jsonify({"message": "✅ Linked to "+ex})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/binance/balance", methods=["POST"])
def binance_balance():
    try:
        uid = request.json.get("uid")
        if uid not in binance_sessions:
            return jsonify({"error": "Not linked"}), 400
        balance = binance_sessions[uid].fetch_balance()
        return jsonify(balance)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/binance/trade", methods=["POST"])
def binance_trade():
    try:
        data = request.json
        uid = data.get("uid")
        symbol = data.get("symbol")
        side = data.get("side")
        qty = float(data.get("quantity", 0))
        if uid not in binance_sessions:
            return jsonify({"error": "Not linked"}), 400
        order = binance_sessions[uid].create_market_order(symbol, side, qty)
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ================== ZERODHA ==================
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "no0ptvria732gj4z")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "dj2mv7mrpge9cqmsankxayxhly0i69k2")

@app.route("/zerodha/login", methods=["POST"])
def zerodha_login():
    try:
        data = request.json
        uid = data.get("uid")
        request_token = data.get("requestToken")
        kite = KiteConnect(api_key=ZERODHA_API_KEY)
        session = kite.generate_session(request_token, api_secret=ZERODHA_API_SECRET)
        kite.set_access_token(session["access_token"])
        zerodha_sessions[uid] = kite
        return jsonify({"message": "✅ Zerodha linked"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/zerodha/balance", methods=["POST"])
def zerodha_balance():
    try:
        uid = request.json.get("uid")
        if uid not in zerodha_sessions:
            return jsonify({"error": "Not logged in"}), 400
        funds = zerodha_sessions[uid].funds()
        return jsonify(funds)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/zerodha/trade", methods=["POST"])
def zerodha_trade():
    try:
        data = request.json
        uid = data.get("uid")
        symbol = data.get("symbol")   # NSE:INFY
        side = data.get("side")
        qty = int(data.get("quantity", 1))
        if uid not in zerodha_sessions:
            return jsonify({"error": "Not logged in"}), 400
        kite = zerodha_sessions[uid]
        order = kite.place_order(
            tradingsymbol=symbol.split(":")[1],
            exchange="NSE",
            transaction_type="BUY" if side.lower()=="buy" else "SELL",
            quantity=qty,
            order_type="MARKET",
            product="CNC",
            variety="regular"
        )
        return jsonify({"message": "✅ Order placed", "order_id": order})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ================== ANGELONE ==================
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "0LmP8dY3")
ANGEL_API_SECRET = os.getenv("ANGEL_API_SECRET", "ba1fb5eb-bbb3-439f-ae93-4c355b412abf")

# ⚠️ Placeholder: token map (must be loaded from AngelOne scrip master)
symbol_token_map = {"INFY-EQ": "3045"}  # Example only

@app.route("/angelone/login", methods=["POST"])
def angel_login():
    try:
        data = request.json
        uid = data.get("uid")
        client_id = data.get("client_id")
        password = data.get("password")
        totp_key = data.get("totp")
        obj = SmartConnect(api_key=ANGEL_API_KEY)
        token_data = obj.generateSession(client_id, password, pyotp.TOTP(totp_key).now())
        angel_sessions[uid] = {
            "client_id": client_id,
            "obj": obj,
            "feed_token": token_data["data"]["feedToken"]
        }
        return jsonify({"message": "✅ AngelOne linked"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/angelone/balance", methods=["POST"])
def angel_balance():
    try:
        uid = request.json.get("uid")
        if uid not in angel_sessions:
            return jsonify({"error": "Not logged in"}), 400
        obj = angel_sessions[uid]["obj"]
        funds = obj.rmsLimit()
        return jsonify(funds)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/angelone/trade", methods=["POST"])
def angel_trade():
    try:
        data = request.json
        uid = data.get("uid")
        symbol = data.get("symbol")   # e.g. INFY-EQ
        side = data.get("side")
        qty = int(data.get("quantity", 1))
        if uid not in angel_sessions:
            return jsonify({"error": "Not logged in"}), 400
        obj = angel_sessions[uid]["obj"]
        if symbol not in symbol_token_map:
            return jsonify({"error": "Symbol not mapped"}), 400
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": symbol_token_map[symbol],
            "transactiontype": "BUY" if side.lower()=="buy" else "SELL",
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "CNC",
            "duration": "DAY",
            "price": 0,
            "squareoff": 0,
            "stoploss": 0,
            "quantity": qty
        }
        orderId = obj.placeOrder(orderparams)
        return jsonify({"message": "✅ AngelOne order placed", "order_id": orderId})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ================== ROOT ==================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "PTH Backend Running ✅"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
