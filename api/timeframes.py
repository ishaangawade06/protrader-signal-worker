import ccxt
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"message": "Timesframes service is live ✅"})

@app.route("/candles", methods=["GET"])
def candles():
    """
    Example: /candles?symbol=BTC/USDT&interval=1h&limit=50
    """
    symbol = request.args.get("symbol", "BTC/USDT")
    interval = request.args.get("interval", "1h")
    limit = int(request.args.get("limit", 50))

    exchange = ccxt.binance()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval, limit=limit)
        data = [
            {
                "time": int(candle[0] / 1000),  # timestamp in seconds
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4]
            }
            for candle in ohlcv
        ]
        return jsonify({"symbol": symbol, "interval": interval, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
