from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import ccxt

app = Flask(__name__)
CORS(app)

# 🔑 Firebase init
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

@app.route("/")
def home():
    return jsonify({"status": "PTH Backend running"})

# ✅ Balance endpoint
@app.route("/balance", methods=["POST"])
def get_balance():
    try:
        data = request.json
        api_key = data.get("apiKey")
        secret = data.get("secret")

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True
        })
        balance = exchange.fetch_balance()
        return jsonify(balance)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ Buy endpoint
@app.route("/buy", methods=["POST"])
def buy_order():
    try:
        data = request.json
        api_key = data.get("apiKey")
        secret = data.get("secret")
        symbol = data.get("symbol", "BTC/USDT")
        amount = float(data.get("amount", 0.001))

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True
        })
        order = exchange.create_market_buy_order(symbol, amount)
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ Sell endpoint
@app.route("/sell", methods=["POST"])
def sell_order():
    try:
        data = request.json
        api_key = data.get("apiKey")
        secret = data.get("secret")
        symbol = data.get("symbol", "BTC/USDT")
        amount = float(data.get("amount", 0.001))

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True
        })
        order = exchange.create_market_sell_order(symbol, amount)
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
