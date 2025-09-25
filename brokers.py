# brokers.py
import os
import time
from datetime import datetime
from typing import Dict, Any

# optional imports (may not be installed in environment)
try:
    from kiteconnect import KiteConnect
except Exception:
    KiteConnect = None

try:
    from smartapi import SmartConnect
except Exception:
    SmartConnect = None

# ---------- Helper wrappers ----------
def _now_iso():
    return datetime.utcnow().isoformat()

# ---------- Zerodha helpers ----------
def zerodha_create_session(api_key: str, request_token: str, api_secret: str = None) -> Dict[str, Any]:
    """
    Exchange request_token for access_token and return session info dict.
    Requires kiteconnect installed.
    """
    if KiteConnect is None:
        raise RuntimeError("kiteconnect library not installed")
    kite = KiteConnect(api_key=api_key)
    # KiteConnect.generate_session expects request_token and api_secret
    # returns {'access_token': '...', 'public_token': '...'}
    sess = kite.generate_session(request_token, api_secret or "")
    # sess may have 'access_token'
    return {
        "access_token": sess.get("access_token"),
        "login_time": _now_iso(),
        "raw": sess
    }

def zerodha_get_balance(api_key: str, access_token: str) -> Dict[str, Any]:
    """
    Fetch usable balance for Zerodha user.
    Returns dict {balance: float, currency: 'INR', raw: {...}}
    """
    if KiteConnect is None:
        raise RuntimeError("kiteconnect library not installed")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    # margins returns dict per segment; using equity/net for demonstration
    margins = kite.margins("equity")  # may raise if token expired
    # margins shape depends on Kite API — attempt to pull useful value
    balance = None
    if isinstance(margins, dict):
        # try common keys
        for key in ("net", "cash", "available"):
            if key in margins:
                balance = margins.get(key)
                break
        # fallback: sum numeric values
        if balance is None:
            numeric_vals = [v for v in margins.values() if isinstance(v, (int, float))]
            balance = sum(numeric_vals) if numeric_vals else 0.0
    else:
        balance = 0.0
    return {"balance": float(balance or 0.0), "currency": "INR", "raw": margins}

def zerodha_place_order(api_key: str, access_token: str, order_payload: dict) -> dict:
    """
    Place an order via KiteConnect. order_payload is per KiteConnect's place_order args.
    Returns Kite response dict.
    """
    if KiteConnect is None:
        raise RuntimeError("kiteconnect library not installed")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    res = kite.place_order(**order_payload)
    return {"result": res, "time": _now_iso()}


# ---------- AngelOne (SmartAPI) helpers ----------
def angel_create_session(api_key: str, client_id: str, password: str, totp: str = None) -> Dict[str, Any]:
    """
    Create session with AngelOne SmartConnect.
    smartapi-python usage varies; this function attempts generateSession flow and returns token/data.
    """
    if SmartConnect is None:
        raise RuntimeError("smartapi-python library not installed")
    smart = SmartConnect(api_key=api_key)
    # SmartConnect.generateSession(...) signature may require client_id + password and TOTP if enabled
    resp = smart.generateSession(client_id, password, smart.generateToken(totp) if totp else None)
    # Response expected to contain tokens; store raw response
    return {"session": resp, "login_time": _now_iso()}

def angel_get_balance(api_key: str, jwt_token: str) -> Dict[str, Any]:
    """
    Use SmartConnect instance to fetch RMS/margin balance (API specifics vary).
    Expectation: smartApi.rmsLimit() returns margin/balance.
    """
    if SmartConnect is None:
        raise RuntimeError("smartapi-python library not installed")
    smart = SmartConnect(api_key=api_key)
    # some smartapi libs expect set_jwt_token or similar — check library docs
    try:
        smart.session = {"jwtToken": jwt_token}
    except Exception:
        pass
    try:
        rms = smart.rmsLimit()  # method name may differ; adjust if needed
    except Exception:
        # fallback: call get profile or funds endpoint
        rms = {}
    # attempt to extract numeric net
    balance = 0.0
    if isinstance(rms, dict):
        for k in ("net", "available", "equity"):
            if k in rms:
                try:
                    balance = float(rms[k])
                    break
                except Exception:
                    pass
    return {"balance": float(balance), "currency": "INR", "raw": rms}

def angel_place_order(api_key: str, jwt_token: str, order_payload: dict) -> dict:
    """
    Place order via AngelOne API wrapper. Signature depends on library.
    """
    if SmartConnect is None:
        raise RuntimeError("smartapi-python library not installed")
    smart = SmartConnect(api_key=api_key)
    try:
        smart.session = {"jwtToken": jwt_token}
    except Exception:
        pass
    res = smart.placeOrder(order_payload) if hasattr(smart, "placeOrder") else {"unsupported": True}
    return {"result": res, "time": _now_iso()}


# ---------- Generic helpers for main.py to call ----------
def get_balance_for_user_broker(broker_key: str, creds: dict) -> dict:
    """
    broker_key: 'zerodha' or 'angelone' or 'binance' or 'exness'
    creds: dict read from Firestore for that user and broker
    Returns: dict {balance, currency, raw}
    """
    bk = broker_key.lower()
    if bk == "zerodha":
        api_key = creds.get("api_key")
        access_token = creds.get("access_token")
        if not api_key or not access_token:
            return {"balance": "Connect Broker"}
        return zerodha_get_balance(api_key, access_token)
    if bk == "angelone":
        api_key = creds.get("api_key")
        jwt_token = creds.get("jwt_token") or creds.get("access_token")
        if not api_key or not jwt_token:
            return {"balance": "Connect Broker"}
        return angel_get_balance(api_key, jwt_token)
    # For Binance/Exness we leave placeholders (ccxt should be used)
    if bk in ("binance", "exness"):
        # placeholder: should be replaced by ccxt client calls in main
        balance = creds.get("balance", 0.0)
        return {"balance": float(balance or 0.0), "currency": "USDT", "raw": {}}
    return {"balance": "Unsupported Broker"}

def place_order_for_user_broker(broker_key: str, creds: dict, order_payload: dict) -> dict:
    bk = broker_key.lower()
    if bk == "zerodha":
        api_key = creds.get("api_key")
        access_token = creds.get("access_token")
        if not api_key or not access_token:
            raise RuntimeError("Zerodha not connected")
        return zerodha_place_order(api_key, access_token, order_payload)
    if bk == "angelone":
        api_key = creds.get("api_key")
        jwt_token = creds.get("jwt_token") or creds.get("access_token")
        if not api_key or not jwt_token:
            raise RuntimeError("AngelOne not connected")
        return angel_place_order(api_key, jwt_token, order_payload)
    if bk in ("binance", "exness"):
        # implement ccxt calls from main.py side (or here)
        return {"result": "ccxt-order-placeholder", "time": _now_iso()}
    raise RuntimeError("Unsupported broker")
