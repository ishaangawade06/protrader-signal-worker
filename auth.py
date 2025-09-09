# auth.py
import os, json
from datetime import datetime, timedelta

KEYS_FILE = "keys.json"  # local JSON storage of keys

def load_keys():
    try:
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_keys(data):
    with open(KEYS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def create_key(name, days=7):
    """Create a new key with expiry (days). If days=0 => lifetime"""
    data = load_keys()
    key = f"{name}_{int(datetime.utcnow().timestamp())}"
    expiry = None if days == 0 else (datetime.utcnow() + timedelta(days=days)).isoformat()
    data[key] = {"created": datetime.utcnow().isoformat(), "expiry": expiry, "active": True}
    save_keys(data)
    return key

def validate_key(key):
    """Check if a key is valid and not expired"""
    data = load_keys()
    if key not in data:
        return False
    k = data[key]
    if not k.get("active", True):
        return False
    expiry = k.get("expiry")
    if expiry and datetime.utcnow() > datetime.fromisoformat(expiry):
        return False
    return True

def deactivate_key(key):
    data = load_keys()
    if key in data:
        data[key]["active"] = False
        save_keys(data)
        return True
    return False
