import json, os, time

KEYS_FILE = "keys.json"

# --- Predefined default keys ---
DEFAULT_KEYS = {
    "owner": {
        "vamya": {"type": "owner", "expires": 0},
        "pthowner16": {"type": "owner", "expires": 0},
    },
    "standard": {
        "pth7": {"type": "user", "expires": 7},      # 7 days
        "key15": {"type": "user", "expires": 15},    # 15 days
        "ishaan30": {"type": "user", "expires": 30}, # 30 days
        "ishaan": {"type": "user", "expires": 0},    # lifetime
    }
}

def load_keys():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_KEYS

def save_keys(data):
    with open(KEYS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def validate_key(key: str) -> bool:
    """Check if key exists and not expired"""
    keys = load_keys()
    for section in keys.values():
        if key in section:
            expires = section[key]["expires"]
            if expires == 0:
                return True  # lifetime or owner
            created = section[key].get("created", int(time.time()))
            if time.time() < created + expires * 86400:
                return True
    return False

def is_owner(key: str) -> bool:
    keys = load_keys()
    return key in keys.get("owner", {})

# Create file if not exists
if not os.path.exists(KEYS_FILE):
    save_keys(DEFAULT_KEYS)
