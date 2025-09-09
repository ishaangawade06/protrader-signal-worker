# auth.py
import os, json, time, hmac, hashlib
from datetime import datetime, timedelta

# Try to init Firebase (optional). If firebase_admin not available or not configured,
# code will fallback to local file-based storage (keys.json).
_db = None
_firebase_initialized = False
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    def _init_firebase():
        global _db, _firebase_initialized
        if _firebase_initialized:
            return _db
        # try env var first (workflow writes serviceAccount.json but we also accept raw JSON)
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        cred = None
        if raw:
            try:
                sa = json.loads(raw)
                cred = credentials.Certificate(sa)
            except Exception:
                # maybe it's base64 or already file content; try write to serviceAccount.json
                try:
                    with open("serviceAccount.json","w") as f:
                        f.write(raw)
                    cred = credentials.Certificate("serviceAccount.json")
                except Exception:
                    cred = None
        elif os.path.exists("serviceAccount.json"):
            cred = credentials.Certificate("serviceAccount.json")
        if cred:
            try:
                firebase_admin.initialize_app(cred)
                _db = firestore.client()
                _firebase_initialized = True
                return _db
            except Exception as e:
                print("Firebase init error:", e)
                _db = None
                _firebase_initialized = False
                return None
        return None

    _db = _init_firebase()
except Exception:
    _db = None
    _firebase_initialized = False

# --- Default keys (the ones you gave) ---
OWNER_KEYS = ["vamya", "pthowner16"]
DEFAULT_KEYS = {
    "pth7": 7,
    "key15": 15,
    "ishaan30": 30,
    "ishaan": 9999999  # treated as lifetime
}

# local fallback store path
_KEYS_FILE = "keys_local.json"

def _load_local_keys():
    if os.path.exists(_KEYS_FILE):
        try:
            with open(_KEYS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    # seed defaults
    d = {}
    for k, days in DEFAULT_KEYS.items():
        d[k] = {"type":"user","days":days,"created":None,"active":True}
    for k in OWNER_KEYS:
        d[k] = {"type":"owner","days":0,"created":None,"active":True}
    with open(_KEYS_FILE,"w") as f:
        json.dump(d,f,indent=2)
    return d

def _save_local_keys(data):
    with open(_KEYS_FILE,"w") as f:
        json.dump(data,f,indent=2)

# --- Helper: Firestore helpers if available ---
def _get_db():
    global _db
    if _firebase_initialized and _db:
        return _db
    return None

def _seed_defaults_to_firestore():
    db = _get_db()
    if not db:
        return
    coll = db.collection("keys")
    # create keys if not exist
    for k, days in DEFAULT_KEYS.items():
        doc = coll.document(k).get()
        if not doc.exists:
            coll.document(k).set({
                "type":"user",
                "days": days,
                "created": None,
                "active": True
            })
    for k in OWNER_KEYS:
        doc = coll.document(k).get()
        if not doc.exists:
            coll.document(k).set({
                "type":"owner",
                "days": 0,
                "created": None,
                "active": True
            })

# call seed at import if firebase is available
if _get_db():
    try:
        _seed_defaults_to_firestore()
    except Exception:
        pass

# --- Admin password (stored in Firestore settings if available) ---
def get_admin_password():
    db = _get_db()
    if db:
        doc = db.collection("settings").document("admin").get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("password", os.environ.get("OWNER_ADMIN_PASS", "vamya"))
    return os.environ.get("OWNER_ADMIN_PASS", "vamya")

def set_admin_password(newpass):
    db = _get_db()
    if db:
        db.collection("settings").document("admin").set({"password": newpass})
        return True
    else:
        # local fallback: store in keys file under special field
        d = _load_local_keys()
        d["_admin_pass"] = newpass
        _save_local_keys(d)
        return True

# --- Key operations (check/create/delete/list/blocking/logging) ---
def check_key(key: str):
    """
    Return (valid: bool, role: str or None, expiry_iso: str or None)
    """
    if not key: return False, None, None
    # owners hardcoded first
    if key in OWNER_KEYS:
        return True, "owner", None

    db = _get_db()
    if db:
        doc = db.collection("keys").document(key).get()
        if doc.exists:
            data = doc.to_dict()
            if not data.get("active", True):
                return False, None, None
            typ = data.get("type", "user")
            days = int(data.get("days", 0) or 0)
            created = data.get("created")
            if not created:
                # set created on first use
                now_iso = datetime.utcnow().isoformat()
                db.collection("keys").document(key).update({"created": now_iso})
                created = now_iso
            if days == 0 or days >= 99999:
                return True, typ, None
            exp = datetime.fromisoformat(created) + timedelta(days=days)
            if datetime.utcnow() < exp:
                return True, typ, exp.isoformat()
            return False, None, None
        # if doc doesn't exist, maybe it's one of DEFAULT_KEYS not seeded; fall through
    # local fallback
    local = _load_local_keys()
    if key in local:
        k = local[key]
        if not k.get("active", True):
            return False, None, None
        if k.get("type") == "owner":
            return True, "owner", None
        days = int(k.get("days",0) or 0)
        created = k.get("created")
        if not created:
            created = datetime.utcnow().isoformat()
            local[key]["created"] = created
            _save_local_keys(local)
        if days == 0 or days >= 99999:
            return True, "user", None
        exp = datetime.fromisoformat(created) + timedelta(days=days)
        if datetime.utcnow() < exp:
            return True, "user", exp.isoformat()
        return False, None, None
    return False, None, None

def create_key(key: str, days:int, creator: str = None):
    db = _get_db()
    if db:
        db.collection("keys").document(key).set({
            "type":"user",
            "days": int(days),
            "created": None,
            "active": True,
            "created_by": creator
        })
        return True
    # local fallback
    local = _load_local_keys()
    local[key] = {"type":"user","days":int(days),"created": None,"active": True, "created_by": creator}
    _save_local_keys(local)
    return True

def delete_key(key: str):
    db = _get_db()
    if db:
        doc = db.collection("keys").document(key)
        doc.set({"active": False}, merge=True)
        return True
    local = _load_local_keys()
    if key in local:
        local[key]["active"] = False
        _save_local_keys(local)
        return True
    return False

def list_keys():
    db = _get_db()
    out = []
    if db:
        docs = db.collection("keys").stream()
        for d in docs:
            dd = d.to_dict()
            dd["_id"] = d.id
            out.append(dd)
        return out
    local = _load_local_keys()
    for k,v in local.items():
        v2 = dict(v)
        v2["_id"] = k
        out.append(v2)
    return out

# --- Device blocking and logging ---
def block_device(device_id: str, reason: str = ""):
    db = _get_db()
    rec = {"device_id": device_id, "blocked_at": datetime.utcnow().isoformat(), "reason": reason}
    if db:
        db.collection("blocked_devices").document(device_id).set(rec)
        return True
    # local fallback
    local = _load_local_keys()
    blocked = local.get("_blocked_devices", {})
    blocked[device_id] = rec
    local["_blocked_devices"] = blocked
    _save_local_keys(local)
    return True

def unblock_device(device_id: str):
    db = _get_db()
    if db:
        db.collection("blocked_devices").document(device_id).delete()
        return True
    local = _load_local_keys()
    blocked = local.get("_blocked_devices", {})
    if device_id in blocked:
        del blocked[device_id]
        local["_blocked_devices"] = blocked
        _save_local_keys(local)
        return True
    return False

def is_device_blocked(device_id: str):
    if not device_id:
        return False
    db = _get_db()
    if db:
        doc = db.collection("blocked_devices").document(device_id).get()
        return doc.exists
    local = _load_local_keys()
    blocked = local.get("_blocked_devices", {})
    return device_id in blocked

def log_usage(key, action, meta: dict):
    """Store key usage logs: key, action, metadata"""
    rec = {
        "key": key,
        "action": action,
        "meta": meta,
        "ts": datetime.utcnow().isoformat()
    }
    db = _get_db()
    if db:
        try:
            db.collection("access_logs").add(rec)
            return True
        except Exception as e:
            print("log_usage error:", e)
            return False
    # local fallback
    local = _load_local_keys()
    logs = local.get("_logs", [])
    logs.append(rec)
    local["_logs"] = logs
    _save_local_keys(local)
    return True
