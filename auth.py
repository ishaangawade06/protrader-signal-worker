# auth.py
import hashlib
from datetime import datetime, timedelta

# ---------- Hash Helper ----------
def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()

# ---------- Save Key ----------
def save_key_to_db(key: str, role: str = "user", days: int = None, db=None):
    """
    Save API key to Firestore.
    - key: API key (string)
    - role: "user" or "owner"
    - days: expiry in days from now (None = no expiry)
    """
    if not db:
        print("⚠️ No Firestore DB connected.")
        return

    expiry = None
    if days:
        expiry = datetime.utcnow() + timedelta(days=days)

    doc_ref = db.collection("keys").document(hash_key(key))
    doc_ref.set({
        "role": role,
        "created": datetime.utcnow().isoformat(),
        "expiry": expiry.isoformat() if expiry else None
    })
    print(f"✅ Key saved: {key} ({role}, expiry={expiry})")

# ---------- Validate Key ----------
def validate_key(key: str, db=None):
    """
    Validate API key against Firestore.
    Returns dict: {valid, role, expiry}
    """
    if not db:
        return {"valid": False}

    try:
        doc = db.collection("keys").document(hash_key(key)).get()
        if not doc.exists:
            return {"valid": False}

        data = doc.to_dict()
        expiry = data.get("expiry")

        if expiry:
            exp = datetime.fromisoformat(expiry)
            if datetime.utcnow() > exp:
                return {"valid": False, "expired": True}

        return {
            "valid": True,
            "role": data.get("role", "user"),
            "expiry": expiry
        }
    except Exception as e:
        print("validate_key error:", e)
        return {"valid": False}
