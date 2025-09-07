import os
import json
import yfinance as yf
import pandas as pd
from flask import Flask, jsonify, request

# ----------------------------
# Load symbols from JSON file
# ----------------------------
with open("symbols.json", "r") as f:
    SYMBOLS_DATA = json.load(f)

def get_all_symbols():
    """Flatten all symbols into a list with market tags."""
    all_symbols = []
    for market, symbols in SYMBOLS_DATA.items():
        for s in symbols:
            all_symbols.append({
                "symbol": s["symbol"],
                "yf_symbol": s["yf_symbol"],
                "name": s["name"],
                "market": market
            })
    return all_symbols

ALL_SYMBOLS = get_all_symbols()

# ----------------------------
# Fetch Data
# ----------------------------
def fetch_yahoo_data(yf_symbol, interval="5m", period="5d"):
    try:
        df = yf.download(tickers=yf_symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            raise RuntimeError(f"No data received for {yf_symbol}")

        # Fix multi-index column issue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower().replace(" ", "_") for c in df.columns]
        else:
            df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

        return df
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {yf_symbol} ({interval}): {e}")

# ----------------------------
# Risk Management
# ----------------------------
def calculate_position_size(balance, risk_percent, entry_price, stop_loss_price):
    """
    Calculate position size based on account balance, risk %, and stop loss.
    """
    risk_amount = balance * (risk_percent / 100.0)
    per_unit_risk = abs(entry_price - stop_loss_price)
    if per_unit_risk == 0:
        return 0
    position_size = risk_amount / per_unit_risk
    return round(position_size, 4)

# ----------------------------
# Flask API
# ----------------------------
app = Flask(__name__)

@app.route("/symbols", methods=["GET"])
def list_symbols():
    """Return all available symbols with markets and names"""
    return jsonify(ALL_SYMBOLS)

@app.route("/timeframes", methods=["GET"])
def timeframes():
    """
    GET /timeframes?symbol=BTC-USD
    Returns list of available intervals for this symbol
    """
    yf_symbol = request.args.get("symbol", "").strip()
    if not yf_symbol:
        return jsonify({"error": "symbol required"}), 400

    intervals = ["1m", "2m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]
    valid = []
    for interval in intervals:
        try:
            df = fetch_yahoo_data(yf_symbol, interval=interval, period="5d")
            if df is not None and not df.empty:
                valid.append(interval)
        except Exception:
            continue

    return jsonify({"symbol": yf_symbol, "valid_timeframes": valid})

@app.route("/position-size", methods=["GET"])
def position_size():
    """
    Example: /position-size?balance=10000&risk_percent=2&entry=2000&stop=1950
    """
    try:
        balance = float(request.args.get("balance", "0"))
        risk_percent = float(request.args.get("risk_percent", "1"))
        entry_price = float(request.args.get("entry", "0"))
        stop_loss_price = float(request.args.get("stop", "0"))

        size = calculate_position_size(balance, risk_percent, entry_price, stop_loss_price)
        return jsonify({
            "balance": balance,
            "risk_percent": risk_percent,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "position_size": size
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ----------------------------
# Signal Processing Worker
# ----------------------------
def process_symbol(yf_symbol, interval="5m"):
    try:
        df = fetch_yahoo_data(yf_symbol, interval=interval, period="5d")
        print(f"✅ Processed {yf_symbol} with {len(df)} rows at interval {interval}")
        return True
    except Exception as e:
        print(f"❌ Error processing {yf_symbol}: {e}")
        return False

if __name__ == "__main__":
    # Manual test run
    for sym in ALL_SYMBOLS:
        process_symbol(sym["yf_symbol"], interval="5m")
    
    # Uncomment to run Flask API locally
    # app.run(host="0.0.0.0", port=5000, debug=True)
