import os
import firebase_admin
from firebase_admin import credentials, firestore
from app import app

# -------------------------------
# Initialize Firebase
# -------------------------------
if not firebase_admin._apps:
    # Get Firebase key JSON from environment variable (Render -> Secrets)
    firebase_key = os.getenv("FIREBASE_SERVICE_ACCOUNT")

    if firebase_key:
        # The secret is stored as a JSON string, so we need to convert it
        cred = credentials.Certificate(eval(firebase_key))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Firebase Firestore connected!")
    else:
        db = None
        print("⚠️ No FIREBASE_SERVICE_ACCOUNT found in environment variables")

# -------------------------------
# Run Flask app
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
