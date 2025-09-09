# auth.py
import os, json, base64
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase either from env FIREBASE_SERVICE_ACCOUNT (JSON or base64)
# or from a local file 'serviceAccount.json' or 'serviceAccountKey.json'.
def init_firebase():
    if firebase_admin._apps:
        return firebase_admin.get_app()

    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if raw:
        # try JSON then base64-decode JSON
        try:
            svc = json.loads(raw)
        except Exception:
            svc = json.loads(base64.b64decode(raw).decode())
        cred = credentials.Certificate(svc)
        firebase_admin.initialize_app(cred)
        return firebase_admin.get_app()

    # try common filenames
    for fname in ("serviceAccount.json", "serviceAccountKey.json"):
        if os.path.exists(fname):
            cred = credentials.Certificate(fname)
            firebase_admin.initialize_app(cred)
            return firebase_admin.get_app()

    # no credentials found
    raise RuntimeError("Firebase service account not found. Set FIREBASE_SERVICE_ACCOUNT secret or upload serviceAccount.json")

# init once
init_firebase()
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

# --- Key helpers ---
def save_key_to_db(key, role="user", days=None):
    data = {
        "role": role,
        "created": datetime.utcnow(),
        "expires": None if days is None else datetime.utcnow() + timedelta(days=int(days))
    }
    db.collection("keys").document(key).set({
        "role": data['role'],
        # Firestore needs native serializable types; store timestamps as ISO strings
        "created": data['created'].isoformat(),
        "expires": None if data['expires'] is None else data['expires'].isoformat()
    })

def load_key_from_db(key):
    doc = db.collection("keys").document(key).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    # convert ISO strings back to datetime for expiry check
    expires = data.get("expires")
    if expires:
        try:
            if datetime.utcnow() > datetime.fromisoformat(expires):
                return None
        except Exception:
            pass
    return data

def validate_key(key: str):
    if not key:
        return {"valid": False}
    # First check Firestore
    try:
        db_data = load_key_from_db(key)
        if db_data:
            role = db_data.get("role", "user")
            return {"valid": True, "role": role}
    except Exception as e:
        print("validate_key firestore error:", e)

    # Fallback to defaults
    info = DEFAULT_KEYS.get(key)
    if info:
        return {"valid": True, "role": info["role"]}
    return {"valid": False}
