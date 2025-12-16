# ================= IMPORTS =================
from flask import Flask, send_from_directory, request, jsonify, Response, session
from datetime import datetime
import os, json, shutil, base64, hashlib

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet


# ================= BASE PATHS =================
BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, 'static')
IDEAS = os.path.join(BASE, 'ideas')
USERS_DIR = os.path.join(BASE, 'users')
USERS_FILE = os.path.join(USERS_DIR, 'users.enc')

os.makedirs(IDEAS, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)


# ================= AUTH SKELETON (STEP 1) =================
ADMIN_USERNAME = os.environ.get("IDEAJOURNAL_ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("IDEAJOURNAL_ADMIN_PASSWORD")
MASTER_KEY = os.environ.get("IDEAJOURNAL_MASTER_KEY")

if not all([ADMIN_USERNAME, ADMIN_PASSWORD, MASTER_KEY]):
    raise RuntimeError(
        "Missing env vars. Set IDEAJOURNAL_ADMIN_USERNAME, IDEAJOURNAL_ADMIN_PASSWORD, IDEAJOURNAL_MASTER_KEY"
    )

def derive_fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

MASTER_FERNET = derive_fernet(MASTER_KEY)
ADMIN_FERNET = derive_fernet(ADMIN_PASSWORD)

def is_logged_in():
    return bool(session.get("user"))

def is_admin():
    return session.get("role") == "admin"


# ================= USER STORE (STEP 2) =================
def load_users():
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        return {}

    try:
        encrypted = open(USERS_FILE, "rb").read()
        decrypted = ADMIN_FERNET.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except Exception as e:
        raise RuntimeError("Failed to decrypt users.enc") from e

def save_users(users: dict):
    raw = json.dumps(users, indent=2).encode("utf-8")
    encrypted = ADMIN_FERNET.encrypt(raw)
    with open(USERS_FILE, "wb") as f:
        f.write(encrypted)


# ================= FLASK APP =================
app = Flask(__name__, static_folder="static")
app.secret_key = "temporary-dev-secret"  # we’ll improve later


# ================= EXISTING ROUTES =================
def clean(s): 
    return ''.join(c for c in s if c.isalnum() or c in ' _-').strip()

def unique(name):
    n = name
    i = 1
    while os.path.exists(os.path.join(IDEAS, n)):
        i += 1
        n = f"{name} ({i})"
    return n

@app.route("/")
def home():
    return send_from_directory(STATIC, "index.html")

@app.route("/dashboard")
def dash():
    return send_from_directory(STATIC, "dashboard.html")

# (your remaining idea routes stay the same — we’ll re-add next step)


if __name__ == "__main__":
    app.run(debug=True)
