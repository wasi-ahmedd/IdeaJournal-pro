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

from functools import wraps
from flask import abort

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

from functools import wraps
from flask import redirect

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper



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
@login_required
def home():
    return send_from_directory(STATIC, "index.html")

@app.route("/dashboard")
@login_required
def dash():
    return send_from_directory(STATIC, "dashboard.html")


# ================= IDEA & PDF ROUTES (STEP 3) =================
def render_pdf(folder):
    json_path = os.path.join(IDEAS, folder, 'idea.json')
    pdf_path = os.path.join(IDEAS, folder, 'idea.pdf')

    if not os.path.exists(json_path):
        return

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    story = []

    def section(title, text):
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"<b>{title}</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        story.append(Paragraph(text or '-', styles['Normal']))

    story.append(Paragraph(f"<b>{data.get('title')}</b>", styles['Title']))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Published on {data.get('dateCreated')} · Idea Journal",
        styles['Italic']
    ))

    section('Summary', data.get('summary'))
    section('Trigger', data.get('trigger'))
    section('Description', data.get('description'))

    story.append(Spacer(1, 12))
    story.append(Paragraph('<b>Use Cases</b>', styles['Heading2']))
    if data.get('useCases'):
        story.append(ListFlowable([
            ListItem(Paragraph(u, styles['Normal'])) for u in data.get('useCases', [])
        ], bulletType='bullet'))
    else:
        story.append(Paragraph('-', styles['Normal']))

    section('Impact', data.get('potentialImpact'))
    section('Challenges', data.get('challenges'))
    section('Current Understanding', data.get('currentUnderstanding'))

    if data.get('updates'):
        story.append(Spacer(1, 12))
        story.append(Paragraph('<b>Updates</b>', styles['Heading2']))
        for u in data.get('updates', []):
            story.append(Paragraph(
                f"<b>{u.get('date')}</b> — {u.get('text')}",
                styles['Normal']
            ))

    story.append(Spacer(1, 30))
    story.append(Paragraph(
        f"Generated on {data.get('generatedAt', '')}",
        styles['Italic']
    ))

    doc.build(story)

@app.route('/api/save-idea', methods=['POST'])
@login_required
def save_idea():
    data = request.json or {}
    if not data.get('title'):
        return jsonify(error='Title required'), 400

    folder = unique(clean(data['title']))
    path = os.path.join(IDEAS, folder)
    os.makedirs(path, exist_ok=True)

    data['dateCreated'] = data.get('dateCreated') or datetime.now().strftime('%Y-%m-%d')
    data.setdefault('updates', [])

    json_path = os.path.join(path, 'idea.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    render_pdf(folder)
    return jsonify(message='Idea saved', folder=folder)


@app.route('/api/dashboard/ideas')
@login_required
def list_ideas():
    ideas = []
    for f in os.listdir(IDEAS):
        p = os.path.join(IDEAS, f, 'idea.json')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
            ideas.append({
                'folder': f,
                'title': d.get('title'),
                'dateCreated': d.get('dateCreated'),
                'summary': d.get('summary'),
                'updatesCount': len(d.get('updates', []))
            })
    return jsonify(ideas)


@app.route('/api/idea/<folder>')
@login_required
def get_idea(folder):
    path = os.path.join(IDEAS, clean(folder), 'idea.json')
    if not os.path.exists(path):
        return jsonify(error='Not found'), 404
    with open(path, encoding='utf-8') as f:
        return Response(json.dumps(json.load(f), indent=2), mimetype='application/json')

@app.route('/api/idea/<folder>', methods=['DELETE'])
@login_required
def delete_idea(folder):
    path = os.path.join(IDEAS, clean(folder))

    if not os.path.exists(path):
        return jsonify(error='Not found'), 404

    shutil.rmtree(path)
    return jsonify(message='Deleted')


@app.route('/api/add-update', methods=['POST'])
@login_required
def add_update():
    data = request.json or {}
    folder = clean(data.get('ideaTitle', ''))
    path = os.path.join(IDEAS, folder, 'idea.json')

    if not os.path.exists(path):
        return jsonify(error='Idea not found'), 404

    with open(path, encoding='utf-8') as f:
        idea = json.load(f)

    idea.setdefault('updates', []).append({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'text': data.get('updateText', '')
    })

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(idea, f, indent=2)

    render_pdf(folder)
    return jsonify(message='Update added')


@app.route('/api/idea/<folder>/pdf')
@login_required
def view_pdf(folder):
    pdf = os.path.join(IDEAS, clean(folder), 'idea.pdf')
    if not os.path.exists(pdf):
        render_pdf(clean(folder))
    return send_from_directory(os.path.dirname(pdf), 'idea.pdf')

# ================= END IDEA & PDF ROUTES =================
# ================= SIGNUP (STEP 4) =================

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # Show signup page
    if request.method == 'GET':
        return send_from_directory('templates', 'signup.html')

    # Handle signup
    data = request.form or request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify(error='Username and password required'), 400

    users = load_users()

    if username in users:
        return jsonify(error='User already exists'), 409

    users[username] = {
        'password_hash': generate_password_hash(password),
        'password_encrypted': MASTER_FERNET.encrypt(password.encode()).decode('utf-8'),
        'created_at': datetime.now().isoformat()
    }

    save_users(users)
    return jsonify(message='Signup successful')

# ================= END SIGNUP =================
# ================= LOGIN (STEP 5) =================

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Show login page
    if request.method == 'GET':
        return send_from_directory('templates', 'login.html')

    data = request.form or request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify(error='Username and password required'), 400

    # ---- Hidden admin login ----
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['user'] = ADMIN_USERNAME
        session['role'] = 'admin'
        return jsonify(redirect='/dashboard')

    users = load_users()
    user = users.get(username)

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify(error='Invalid credentials'), 401

    session['user'] = username
    session['role'] = 'user'
    return jsonify(redirect='/dashboard')

# ================= END LOGIN =================


# (your remaining idea routes stay the same — we’ll re-add next step)
# ================= ADMIN PAGE (STEP 7) =================
from flask import render_template

@app.route('/admin')
@admin_required
def admin_page():
    users = load_users()
    return render_template('admin.html', users=users)


# ================= END ADMIN PAGE =================


if __name__ == "__main__":
    app.run(debug=True)
