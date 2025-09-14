# signals.py
import pandas as pd
import numpy as np
from datetime import datetime

def add_indicators(df):
    df = df.copy()
    close = df['close'].astype(float)
    # EMAs & SMAs
    df['ema_fast'] = close.ewm(span=12, adjust=False).mean()
    df['ema_slow'] = close.ewm(span=26, adjust=False).mean()
    df['sma9'] = close.rolling(9).mean()
    df['sma21'] = close.rolling(21).mean()
    # RSI
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs.fillna(0)))
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    # Bollinger Bands
    df['bb_mid'] = close.rolling(20).mean()
    df['bb_std'] = close.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
    # volume simple smoothing (if available)
    if 'volume' in df.columns:
        df['vol_sma'] = df['volume'].rolling(20).mean()
    return df

def compute_support_resistance(df, lookback=120):
    closes = df['close'].iloc[-lookback:]
    if len(closes) < 5:
        return [float(closes.min())], [float(closes.max())]
    # find local minima/maxima using rolling window
    highs = closes.rolling(5, center=True).apply(lambda x: 1 if x[2]==x.max() else 0, raw=True)
    lows  = closes.rolling(5, center=True).apply(lambda x: 1 if x[2]==x.min() else 0, raw=True)
    supports = list(closes[lows==1].round(4).unique())[-3:]
    resistances = list(closes[highs==1].round(4).unique())[-3:]
    if not supports:
        supports = [round(float(closes.min()),4)]
    if not resistances:
        resistances = [round(float(closes.max()),4)]
    return supports, resistances

def hybrid_signal(df):
    """
    Input: pandas DataFrame with columns open, high, low, close, volume (index datetime)
    Output: dict with signal, confidence, reasons, meta
    """
    df = df.copy()
    df = add_indicators(df)
    if len(df) < 5:
        return {
            "signal": "HOLD",
            "confidence": 0.0,
            "reasons": ["insufficient_data"],
            "meta": {}
        }

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0.0
    reasons = []

    # Trend filter: EMA
    if last['ema_fast'] > last['ema_slow']:
        score += 0.30
        reasons.append("Trend Up (EMA)")
    else:
        score -= 0.30
        reasons.append("Trend Down (EMA)")

    # SMA crossover quick confirmation
    if prev['sma9'] <= prev['sma21'] and last['sma9'] > last['sma21']:
        score += 0.20
        reasons.append("SMA cross up")
    if prev['sma9'] >= prev['sma21'] and last['sma9'] < last['sma21']:
        score -= 0.20
        reasons.append("SMA cross down")

    # MACD confirmation
    if prev['macd'] <= prev['macd_signal'] and last['macd'] > last['macd_signal']:
        score += 0.15
        reasons.append("MACD bullish")
    if prev['macd'] >= prev['macd_signal'] and last['macd'] < last['macd_signal']:
        score -= 0.15
        reasons.append("MACD bearish")

    # RSI bias (protect against extremes)
    rsi = float(last.get('rsi', 50))
    if rsi < 30:
        score += 0.10
        reasons.append(f"RSI {rsi:.1f} oversold")
    elif rsi > 70:
        score -= 0.10
        reasons.append(f"RSI {rsi:.1f} overbought")

    # Bollinger breakout minor weight
    if last['close'] > last['bb_upper']:
        score += 0.05
        reasons.append("BB breakout up")
    if last['close'] < last['bb_lower']:
        score -= 0.05
        reasons.append("BB breakout down")

    # Volume spike adds confidence (if volume available)
    if 'volume' in df.columns and not np.isnan(last.get('vol_sma', np.nan)):
        if last['volume'] > 1.5 * (last.get('vol_sma') or 1):
            score += 0.05
            reasons.append("Volume spike")

    # Normalize to confidence 0..1 (rough)
    confidence = max(0.0, min(1.0, (score + 1.0) / 2.0))

    if score > 0.25:
        signal = "BUY"
    elif score < -0.25:
        signal = "SELL"
    else:
        signal = "HOLD"

    supports, resistances = compute_support_resistance(df)

    entry = float(last['close'])
    stop_loss = round(entry * 0.99, 8)   # default 1% SL (heuristic)
    take_profit = round(entry * 1.02, 8) # default 2% TP

    meta = {
        "sma9": float(last['sma9']),
        "sma21": float(last['sma21']),
        "ema_fast": float(last['ema_fast']),
        "ema_slow": float(last['ema_slow']),
        "macd": float(last['macd']),
        "macd_signal": float(last['macd_signal']),
        "rsi": float(rsi),
        "bb_upper": float(last['bb_upper']),
        "bb_lower": float(last['bb_lower']),
        "supports": supports,
        "resistances": resistances,
        "last_price": entry,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "timestamp": datetime.utcnow().isoformat()
    }

    return {
        "signal": signal,
        "confidence": round(float(confidence), 4),
        "reasons": reasons,
        "meta": meta
    }
