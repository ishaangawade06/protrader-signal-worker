from flask import Blueprint, request, jsonify
import yfinance as yf
import json, os

bp = Blueprint("timeframes", __name__)

# Same list of valid Yahoo Finance intervals
VALID_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo"
]

SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "..", "symbols.json")

def load_symbols():
    with open(SYMBOLS_FILE, "r") as f:
        return json.load(f)

def save_symbols(data):
    with open(SYMBOLS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def map_symbol(symbol, market):
    """Map user symbol to Yahoo Finance ticker"""
    if market == "crypto":
        return symbol.replace("USDT", "-USD")
    elif market == "forex":
        return symbol + "=X"
    else:
        return symbol

def verify_timeframe(symbol, market, interval):
    """Try fetching minimal data to confirm if timeframe works"""
    yf_symbol = map_symbol(symbol, market)
    try:
        df = yf.download(tickers=yf_symbol, period="5d", interval=interval, progress=False)
        return not df.empty
    except Exception:
        return False

@bp.route("/timeframes", methods=["GET"])
def timeframes():
    """
    GET /timeframes?symbol=BTCUSDT&market=crypto&verify=true
    - symbol: required
    - market: crypto/forex/indian
    - verify: optional (true/false)
    """
    symbol = request.args.get("symbol", "").strip()
    market = request.args.get("market", "stock").strip()
    verify = request.args.get("verify", "false").lower() == "true"

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    available = []
    for interval in VALID_INTERVALS:
        if verify:
            if verify_timeframe(symbol, market, interval):
                available.append(interval)
        else:
            available.append(interval)

    # 🔹 Update symbols.json so user only has valid timeframes
    data = load_symbols()
    for s in data:
        if s["symbol"] == symbol and s.get("market", "stock") == market:
            s["timeframes"] = available
    save_symbols(data)

    return jsonify({
        "symbol": symbol,
        "market": market,
        "timeframes": available,
        "verified": verify
    })
