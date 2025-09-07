# signals.py
"""
Signal engine for ProTraderHack:
- add_indicators(df): returns df with indicators
- rule_based_signal(df): deterministic BUY/SELL/HOLD with reasons
- ml_predict(features): returns confidence 0..1 using a tiny placeholder model
- hybrid_signal(df): runs TA rules + ML confidence and returns result dict
"""

import os
import pickle
import numpy as np
import pandas as pd

from sklearn.linear_model import LogisticRegression

MODEL_FILE = os.path.join("output", "signal_model.pkl")
os.makedirs("output", exist_ok=True)


# ------------------------
# Helpers
# ------------------------
def _get_close_series(df):
    """Find a close price column robustly and return it as float Series."""
    for col in df.columns:
        if "close" in str(col).lower():
            return df[col].astype(float).reset_index(drop=True)
    # fallback: try last numeric column
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if numeric_cols:
        return df[numeric_cols[-1]].astype(float).reset_index(drop=True)
    raise KeyError("No close column found in dataframe")


# ------------------------
# Indicators
# ------------------------
def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    close = _get_close_series(df)

    # Moving averages
    df["sma9"] = close.rolling(9, min_periods=1).mean()
    df["sma21"] = close.rolling(21, min_periods=1).mean()

    # RSI (smoothed)
    delta = close.diff().fillna(0.0)
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs.fillna(0)))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # momentum
    df["momentum"] = close.diff().fillna(0.0)

    # keep close column normalized name
    df["close"] = close

    return df


# ------------------------
# Rule-based deterministic signal
# ------------------------
def rule_based_signal(df):
    """
    Returns (signal, reasons)
    signal in {"BUY","SELL","HOLD"}
    """
    if df.shape[0] < 5:
        return "HOLD", ["insufficient_data"]

    last = df.iloc[-1]
    prev = df.iloc[-2]

    reasons = []
    cross_up = (prev["sma9"] <= prev["sma21"]) and (last["sma9"] > last["sma21"])
    cross_down = (prev["sma9"] >= prev["sma21"]) and (last["sma9"] < last["sma21"])
    macd_up = (prev["macd"] <= prev["macd_signal"]) and (last["macd"] > last["macd_signal"])
    macd_down = (prev["macd"] >= prev["macd_signal"]) and (last["macd"] < last["macd_signal"])
    rsi = float(last.get("rsi", 50.0))

    if cross_up and macd_up and rsi < 75:
        reasons = ["sma_cross_up", "macd_confirm", f"rsi={rsi:.1f}"]
        return "BUY", reasons

    if cross_down and macd_down and rsi > 25:
        reasons = ["sma_cross_down", "macd_confirm", f"rsi={rsi:.1f}"]
        return "SELL", reasons

    return "HOLD", ["no_strong_confirmation"]


# ------------------------
# Simple placeholder ML model (logistic regression)
# ------------------------
def train_placeholder_model():
    """Train and save a tiny synthetic logistic regression model (first-run only)."""
    # synthetic features
    rng = np.random.RandomState(1)
    X = rng.randn(500, 4)
    # create a simple label function (synthetic)
    y = ((X[:, 0] + 0.2 * X[:, 1]) > 0).astype(int)
    model = LogisticRegression(max_iter=200)
    model.fit(X, y)
    with open(MODEL_FILE, "wb") as fh:
        pickle.dump(model, fh)


def ml_predict(features):
    """
    Accepts array-like features (len 4) and returns confidence in [0..1].
    If model missing, trains a small placeholder model first.
    """
    features = np.asarray(features).reshape(1, -1)
    try:
        if not os.path.exists(MODEL_FILE):
            train_placeholder_model()
        with open(MODEL_FILE, "rb") as fh:
            model = pickle.load(fh)
        prob = model.predict_proba(features)[0, 1]
        return float(np.clip(prob, 0.0, 1.0))
    except Exception:
        return 0.5  # neutral confidence on errors


# ------------------------
# Hybrid signal function (used by main.py)
# ------------------------
def hybrid_signal(df):
    """
    Input: dataframe with price data (must contain a close column)
    Output: dict {signal, reasons, confidence}
    """
    try:
        df = add_indicators(df)
    except Exception as e:
        return {"signal": "HOLD", "reasons": [f"indicator_error:{e}"], "confidence": 0.0}

    signal, reasons = rule_based_signal(df)

    # construct ML features from last row
    if df.shape[0] < 2:
        confidence = 0.0
    else:
        last = df.iloc[-1]
        prev_close = df["close"].iloc[-2] if df.shape[0] >= 2 else df["close"].iloc[-1]
        features = [
            float(last.get("macd", 0.0)),
            float(last.get("rsi", 50.0)),
            float(last.get("sma9", 0.0) - last.get("sma21", 0.0)),
            float(last.get("close", 0.0) - prev_close),
        ]
        confidence = ml_predict(features)

    return {"signal": signal, "reasons": reasons, "confidence": float(confidence)}
