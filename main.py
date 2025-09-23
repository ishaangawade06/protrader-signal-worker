import os
import json
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

from flask import Flask, request, jsonify
from flask_cors import CORS

import ccxt
from kiteconnect import KiteConnect
from smartapi import SmartConnect  # AngelOne

# ------------------ FIREBASE INIT ------------------
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ------------------ FLASK APP ------------------
app = Flask(__name__)
CORS(app)

# ------------------ BROKER HELPERS ------------------

def get_binance_client(api_key, secret_key):
    return ccxt.binance({
        "apiKey": api_key,
        "secret": secret_key
    })

def get_exness_client(api_key, secret_key):
    return ccxt.exness({
        "apiKey": api_key,
        "secret": secret_key
    })

def get_zerodha_client(api_key, secret_key):
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(secret_key)
    return kite

def get_angel_client(api_key, secret_key):
    smart = SmartConnect(api_key=api_key)
    smart.generateSession(api_key, secret_key)
    return smart

# ------------------ ROUTES ------------------

@app.route("/deposit", methods=["POST"])
def deposit():
    try:
        data = request.json
        broker = data.get("broker")
        api_key = data.get("api_key")
        secret_key = data.get("secret_key")
        amount = data.get("amount")

        tx_id = f"tx_{int(datetime.utcnow().timestamp())}"
        ref = db.collection("transactions").document(tx_id)
        ref.set({
            "broker": broker,
            "amount": amount,
            "type": "deposit",
            "status": "processing",
            "created_at": datetime.utcnow().isoformat()
        })

        if broker in ["binance", "exness"]:
            # Direct API transfer simulation
            ref.update({"status": "completed"})
            return jsonify({"status": "completed", "tx_id": tx_id})

        elif broker == "zerodha":
            return jsonify({
                "status": "redirect",
                "url": "https://kite.zerodha.com/funds"
            })

        elif broker == "angelone":
            return jsonify({
                "status": "redirect",
                "url": "https://trade.angelone.in/funds"
            })

        else:
            return jsonify({"error": "Unsupported broker"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/withdraw", methods=["POST"])
def withdraw():
    try:
        data = request.json
        broker = data.get("broker")
        api_key = data.get("api_key")
        secret_key = data.get("secret_key")
        amount = data.get("amount")

        tx_id = f"tx_{int(datetime.utcnow().timestamp())}"
        ref = db.collection("transactions").document(tx_id)
        ref.set({
            "broker": broker,
            "amount": amount,
            "type": "withdraw",
            "status": "processing",
            "created_at": datetime.utcnow().isoformat()
        })

        if broker in ["binance", "exness"]:
            # Direct API withdrawal simulation
            ref.update({"status": "completed"})
            return jsonify({"status": "completed", "tx_id": tx_id})

        elif broker == "zerodha":
            return jsonify({
                "status": "redirect",
                "url": "https://kite.zerodha.com/funds"
            })

        elif broker == "angelone":
            return jsonify({
                "status": "redirect",
                "url": "https://trade.angelone.in/funds"
            })

        else:
            return jsonify({"error": "Unsupported broker"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return jsonify({"message": "PTH backend running"})

# ------------------ MAIN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
