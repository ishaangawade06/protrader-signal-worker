from flask import Flask, request, jsonify
from flask_cors import CORS
import ccxt
from kiteconnect import KiteConnect

app = Flask(__name__)
CORS(app)

# Zerodha config (hardcoded for now)
ZERODHA_API_KEY = "no0ptvria732gj4z"
ZERODHA_API_SECRET = "dj2mv7mrpge9cqmsankxayxhly0i69k2"
zerodha_sessions = {}

@app.route("/")
def home():
    return jsonify({"message": "ProTraderHack Backend Running"})

# Balance
@app.route("/balance", methods=["POST"])
def get_balance():
    try:
        data=request.json
        broker=data.get("name")
        api_key=data.get("apiKey")
        secret=data.get("secretKey")
        token=data.get("token")

        if broker in ["binance","exness"]:
            exchange=getattr(ccxt, broker)({
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True
            })
            balance=exchange.fetch_balance()
            return jsonify(balance)

        elif broker=="zerodha":
            return jsonify({"broker":"zerodha","message":"Zerodha account requires login. Use /zerodha/login."})

        elif broker=="angelone":
            return jsonify({"broker":"angelone","message":"AngelOne support coming soon."})

        elif broker=="quotex":
            return jsonify({"error":"Quotex support coming soon."})

        else:
            return jsonify({"error":"Unsupported broker"}),400
    except Exception as e:
        return jsonify({"error": str(e)}),400

# Trade
@app.route("/trade", methods=["POST"])
def place_trade():
    try:
        data=request.json
        broker=data.get("name")
        api_key=data.get("apiKey")
        secret=data.get("secretKey")
        symbol=data.get("symbol")
        side=data.get("side")
        amount=float(data.get("amount", 0.001))

        if broker in ["binance","exness"]:
            exchange=getattr(ccxt, broker)({
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True
            })
            order=exchange.create_market_order(symbol, side, amount)
            return jsonify(order)

        elif broker=="zerodha":
            return jsonify({"error":"Use /zerodha/trade endpoint for Zerodha"}),400

        elif broker=="angelone":
            return jsonify({"error":"AngelOne trading coming soon."})

        elif broker=="quotex":
            return jsonify({"error":"Quotex trading coming soon."})

        else:
            return jsonify({"error":"Unsupported broker"}),400
    except Exception as e:
        return jsonify({"error": str(e)}),400

# Zerodha login
@app.route("/zerodha/login", methods=["GET"])
def zerodha_login():
    user_id=request.args.get("uid")
    kite=KiteConnect(api_key=ZERODHA_API_KEY)
    login_url=kite.login_url()
    zerodha_sessions[user_id]={"kite":kite}
    return jsonify({"login_url": login_url})

@app.route("/zer
