# api/timeframes.py
import os, json, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app)

# static supported intervals per market (base guidance)
SUPPORTED_INTERVALS = {
    "crypto": ["1m","2m","5m","15m","30m","60m","90m","1d","5d","1wk","1mo","3mo"],
    "indian": ["5m","15m","30m","60m","1d","5d","1wk","1mo","3mo"],
    "forex":  ["15m","30m","60m","1d","5d","1wk","1mo","3mo"],
    "us":     ["1m","2m","5m","15m","30m","60m","90m","1d","5d","1wk","1mo","3mo"]
}

# simple in-memory cache: { cache_key: (expire_ts, result_list) }
_AVAIL_CACHE = {}
CACHE_TTL_SECONDS = int(os.environ.get("TIMEFRAME_CACHE_TTL", "3600"))  # default 1 hour

def infer_market_from_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    # explicit NSE suffix
    if s.endswith(".NS"):
        return "indian"
    # crypto common suffixes
    if s.endswith("USDT") or s.endswith("-USD") or s.endswith("BTC") or s.endswith("ETH"):
        return "crypto"
    # forex / commodities like XAUUSD, EURUSD, GBPUSD, USDINR
    # many forex tickers are 6 letters ending with USD or similar
    if len(s) >= 6 and (s.endswith("USD") or s.endswith("INR") or s.endswith("EUR")):
        return "forex"
    # fallback to US
    return "us"

def _yf_symbol_for_market(symbol: str, market: str) -> str:
    s = symbol.strip()
    if market == "crypto":
        if s.endswith("USDT"):
            return s[:-4] + "-USD"
        if s.endswith("USD"):
            return s[:-3] + "-USD"
        return s
    if market == "forex":
        # yahoo: XAUUSD -> XAUUSD=X ; EURUSD -> EURUSD=X
        if s.endswith("=X"):
            return s
        return s + "=X"
    # indian, us equities: pass through
    return s

def _verify_interval_available(yf_symbol: str, interval: str) -> bool:
    """
    Try a minimal yfinance download for this interval. Return True if data present.
    Keep call lightweight: small period per interval type.
    """
    try:
        # choose short period for intraday intervals
        period = "7d" if interval in ["1m","2m","5m","15m","30m"] else "1y"
        df = yf.download(tickers=yf_symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return False
        # flatten possible MultiIndex and check 'close' presence
        cols = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        cols_lower = [str(c).lower() for c in cols]
        return 'close' in cols_lower and len(df) > 0
    except Exception:
        return False

@app.route("/timeframes", methods=["GET"])
def timeframes():
    """
    GET /timeframes?symbol=BTCUSDT&market=crypto&verify=true
    - symbol: required (or you can provide market param)
    - market: optional (if absent, we infer)
    - verify: optional (true/false). If true the server will try to verify each timeframe actually returns data (slower).
    """
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error":"symbol required (e.g. BTCUSDT or RELIANCE.NS)"}), 400

    market = request.args.get("
