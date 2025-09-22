import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# init firebase
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

def cleanup():
    snap = db.collection("keys").get()
    count = 0
    for doc in snap:
        data = doc.to_dict()
        exp = data.get("expiry")
        if exp:
            try:
                if datetime.utcnow() > datetime.fromisoformat(exp):
                    db.collection("keys").document(doc.id).delete()
                    count += 1
            except Exception as e:
                print("skip", e)
    print("Deleted", count, "expired keys")

if __name__ == "__main__":
    cleanup()
