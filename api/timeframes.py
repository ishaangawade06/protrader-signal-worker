from flask import Blueprint, request, jsonify
import yfinance as yf

timeframes_bp = Blueprint("timeframes", __name__)

# Mapping of allowed intervals per market
ALLOWED_INTERVALS = {
    "crypto": ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"],
    "indian": ["5m", "15m", "30m", "1h", "1d", "1wk"],
    "forex": ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
}

def infer_market(symbol: str):
    """Very basic symbol inference"""
    if symbol.endswith("USDT"):
        return "crypto"
    if symbol.endswith(".NS"):
        return "indian"
    if symbol.endswith("USD") or symbol in ["XAUUSD", "EURUSD", "GBPUSD"]:
        return "forex"
    return None

def verify_interval(symbol, interval):
    """
    Try to fetch small data with yfinance to verify if timeframe works
    """
    try:
        df = yf.download(tickers=symbol, period="1d", interval=interval, progress=False)
        return not df.empty
    except Exception:
        return False

@timeframes_bp.route("/timeframes", methods=["GET"])
def timeframes():
    """
    GET /timeframes?symbol=BTCUSDT&market=crypto&verify=true
    - symbol: required (e.g. BTCUSDT, RELIANCE.NS, XAUUSD)
    - market: optional (crypto, indian, forex). If absent, inferred.
    - verify: optional (true/false). If true, server will verify each timeframe.
    """
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol required (e.g. BTCUSDT, RELIANCE.NS, XAUUSD)"}), 400

    market = request.args.get("market", "").strip()
    if not market:
        market = infer_market(symbol)

    if not market or market not in ALLOWED_INTERVALS:
        return jsonify({"error": f"could not infer market for {symbol}"}), 400

    verify = request.args.get("verify", "false").lower() == "true"

    intervals = ALLOWED_INTERVALS[market]

    if verify:
        valid = []
        for interval in intervals:
            if verify_interval(symbol, interval):
                valid.append(interval)
        intervals = valid

    return jsonify({
        "symbol": symbol,
        "market": market,
        "intervals": intervals
    })
