import os
import json
import yfinance as yf
from flask import Flask, request, jsonify

app = Flask(__name__)

# Path to your symbols.json file
SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "..", "symbols.json")

AVAILABLE_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m",
    "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
]

def verify_timeframes(symbol, market):
    """
    Try downloading data for each timeframe and keep only those that work.
    """
    working = []
    yf_symbol = symbol
    if market == "crypto":
        yf_symbol = symbol.replace("USDT", "-USD")
    elif market == "forex":
        yf_symbol = symbol + "=X"

    for interval in AVAILABLE_INTERVALS:
        try:
            df = yf.download(tickers=yf_symbol, period="5d", interval=interval, progress=False)
            if not df.empty:
                working.append(interval)
        except Exception:
            continue
    return working

@app.route("/timeframes", methods=["GET"])
def timeframes():
    """
    GET /timeframes?symbol=BTCUSDT&market=crypto&refresh=true
    """
    symbol = request.args.get("symbol", "").strip()
    market = request.args.get("market", "").strip()
    refresh = request.args.get("refresh", "false").lower() == "true"

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    result = {"symbol": symbol, "market": market, "available_timeframes": AVAILABLE_INTERVALS}

    if refresh:
        valid = verify_timeframes(symbol, market)
        result["available_timeframes"] = valid

        # 🔹 Auto-update symbols.json
        try:
            if os.path.exists(SYMBOLS_FILE):
                with open(SYMBOLS_FILE, "r") as f:
                    symbols_data = json.load(f)
            else:
                symbols_data = []

            # Find if symbol exists already
            updated = False
            for item in symbols_data:
                if item["symbol"] == symbol:
                    item["timeframes"] = valid
                    updated = True
                    break

            if not updated:
                symbols_data.append({"symbol": symbol, "market": market, "timeframes": valid})

            with open(SYMBOLS_FILE, "w") as f:
                json.dump(symbols_data, f, indent=2)
        except Exception as e:
            return jsonify({"error": f"failed to update symbols.json: {str(e)}"}), 500

    return jsonify(result)
