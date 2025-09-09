# auth.py
import os
from datetime import datetime, timedelta

# --- Hardcoded keys ---
OWNER_KEYS = ["vamya", "pthowner16"]   # never expire
DEFAULT_KEYS = {
    "pth7": 7,        # 7 days
    "key15": 15,      # 15 days
    "ishaan30": 30,   # 30 days
    "ishaan": 99999,  # lifetime (effectively never expires)
}

# Memory store for issued key expiries
ISSUED = {}  # key -> expiry datetime

def check_key(key: str):
    """
    Validate API key.
    Returns (valid: bool, role: str, expires: datetime|None)
    """
    if not key:
        return False, None, None

    # 1. Owners (super admin)
    if key in OWNER_KEYS:
        return True, "owner", None

    # 2. Default keys (timed)
    if key in DEFAULT_KEYS:
        if key not in ISSUED:
            days = DEFAULT_KEYS[key]
            if days >= 99999:
                exp = None  # lifetime
            else:
                exp = datetime.utcnow() + timedelta(days=days)
            ISSUED[key] = exp
        exp = ISSUED[key]
        if exp is None or exp > datetime.utcnow():
            return True, "user", exp
        return False, None, None

    # 3. TODO: Firestore dynamic keys
    # If you want, here we can connect to Firestore to fetch keys created by owner.

    return False, None, None
