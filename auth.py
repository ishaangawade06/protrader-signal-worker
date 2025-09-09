# auth.py
import json
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

# --- Firebase Init ---
try:
    firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate("serviceAccountKey.json")  # download from Firebase console
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- Default Keys (fallback if Firestore empty) ---
DEFAULT_KEYS = {
    "vamya": {"role": "owner", "expires": None},
    "pthowner16": {"role": "owner", "expires": None},
    "pth7": {"role": "user", "expires": 7},
    "key15": {"role": "user", "expires": 15},
    "ishaan30": {"role": "user", "expires": 30},
    "ishaan": {"role": "user", "expires": None},  # lifetime
}

# --- Helper Functions ---
def save_key_to_db(key, role="user", days=None):
    data = {
        "role": role,
        "created": datetime.utcnow(),
        "expires": None if days is None else datetime.utcnow() + timedelta(days=days)
    }
    db.collection("keys").document(key).set(data)

def load_key_from_db(key):
    doc = db.collection("keys").document(key).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    if data.get("expires") and datetime.utcnow() > data["expires"]:
        return None  # expired
    return data

def validate_key(key: str):
    """Check if key is valid (Firestore first, fallback to DEFAULT_KEYS)."""
    # First check Firestore
    db_data = load_key_from_db(key)
    if db_data:
        return {"valid": True, "role": db_data.get("role", "user")}

    # Then check default keys
    if key in DEFAULT_KEYS:
        info = DEFAULT_KEYS[key]
        if info["expires"] is None:
            return {"valid": True, "role": info["role"]}
        else:
            return {"valid": True, "role": info["role"], "days": info["expires"]}
    return {"valid": False}
