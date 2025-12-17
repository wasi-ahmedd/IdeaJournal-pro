# ================= IMPORTS =================
from flask import Flask, send_from_directory, request, jsonify, Response, session
from datetime import datetime
import os, json, shutil, base64, hashlib

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet, InvalidToken
import uuid

from io import BytesIO

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


def derive_user_fernet(username: str, password: str) -> Fernet:
    """
    Derive a per-user Fernet key from username + password.
    Stored ONLY in session memory.
    """
    raw = hashlib.sha256((username + password).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


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

def get_user_fernet():
    if 'ukey' not in session:
        raise RuntimeError("User key missing (not logged in)")
    return Fernet(base64.urlsafe_b64encode(session['ukey']))


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

from flask import render_template, redirect

@app.route('/')
def home():
    if session.get("user"):
        return redirect('/dashboard')
    return render_template('home.html')


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

def render_pdf_bytes(data: dict) -> bytes:
    buffer = BytesIO()

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer,
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
        f"Generated on {datetime.now().isoformat()}",
        styles['Italic']
    ))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    return pdf

@app.route('/api/save-idea', methods=['POST'])
@login_required
def save_idea():
    data = request.json or {}

    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()

    if not title:
        return jsonify(error='Title required'), 400

    # get logged-in user info
    user_id = session['user_id']
    fernet = get_user_fernet()

    # create idea folder
    idea_id = f"idea_{uuid.uuid4().hex}"
    idea_dir = os.path.join(IDEAS, f"user_{user_id}", idea_id)
    os.makedirs(idea_dir, exist_ok=True)

    # -------- encrypt idea JSON --------
    idea_payload = {
    "title": data.get("title", ""),
    "dateCreated": data.get("dateCreated") or datetime.now().strftime('%Y-%m-%d'),
    "summary": data.get("summary", ""),
    "trigger": data.get("trigger", ""),
    "description": data.get("description", ""),
    "useCases": data.get("useCases", []),
    "potentialImpact": data.get("potentialImpact", ""),
    "challenges": data.get("challenges", ""),
    "currentUnderstanding": data.get("currentUnderstanding", ""),
    "updates": data.get("updates", [])
}


    enc_idea = fernet.encrypt(
        json.dumps(idea_payload).encode('utf-8')
    )

    with open(os.path.join(idea_dir, 'idea.enc'), 'wb') as f:
        f.write(enc_idea)

    # -------- generate + encrypt PDF --------
    pdf_bytes = render_pdf_bytes(idea_payload)  # same data, no disk write
    enc_pdf = fernet.encrypt(pdf_bytes)

    with open(os.path.join(idea_dir, 'pdf.enc'), 'wb') as f:
        f.write(enc_pdf)

    # -------- safe metadata --------
    meta = {
        "id": idea_id,
        "title": title,
        "created_at": datetime.now().isoformat()
    }

    with open(os.path.join(idea_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)

    return jsonify(message='Idea saved securely', idea_id=idea_id)

@app.route('/api/idea/<idea_id>', methods=['GET'])
@login_required
def open_idea(idea_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify(error='Unauthorized'), 401

    idea_dir = os.path.join(IDEAS, f"user_{user_id}", idea_id)
    idea_enc_path = os.path.join(idea_dir, 'idea.enc')

    if not os.path.exists(idea_enc_path):
        return jsonify(error='Idea not found'), 404

    try:
        fernet = get_user_fernet()

        with open(idea_enc_path, 'rb') as f:
            enc_data = f.read()

        idea_json = fernet.decrypt(enc_data)
        data = json.loads(idea_json.decode('utf-8'))

        return jsonify(data)

    except Exception as e:
        return jsonify(error='Failed to decrypt idea'), 500


@app.route('/api/my-ideas', methods=['GET'])
@login_required
def my_ideas():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    user_dir = os.path.join(IDEAS, f"user_{user_id}")
    ideas = []

    if not os.path.exists(user_dir):
        return jsonify([])

    for idea_id in os.listdir(user_dir):
        idea_path = os.path.join(user_dir, idea_id)
        meta_path = os.path.join(idea_path, 'meta.json')

        if not os.path.isdir(idea_path):
            continue
        if not os.path.exists(meta_path):
            continue

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                ideas.append(meta)
        except Exception:
            continue

    # newest first
    ideas.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify(ideas)



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

import shutil

@app.route('/api/idea/<idea_id>', methods=['DELETE'])
@login_required
def delete_idea(idea_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify(error='Unauthorized'), 401

    idea_dir = os.path.join(IDEAS, f"user_{user_id}", idea_id)

    if not os.path.exists(idea_dir):
        return jsonify(error='Idea not found'), 404

    try:
        shutil.rmtree(idea_dir)
        return jsonify(message='Idea deleted successfully')
    except Exception:
        return jsonify(error='Failed to delete idea'), 500



@app.route('/api/add-update', methods=['POST'])
@login_required
def add_update():
    data = request.json or {}

    idea_id = data.get('ideaId')
    update_text = (data.get('updateText') or '').strip()

    if not idea_id or not update_text:
        return jsonify(error='Invalid update data'), 400

    user_id = session.get('user_id')
    idea_dir = os.path.join(IDEAS, f"user_{user_id}", idea_id)
    idea_enc_path = os.path.join(idea_dir, 'idea.enc')
    pdf_enc_path = os.path.join(idea_dir, 'pdf.enc')

    if not os.path.exists(idea_enc_path):
        return jsonify(error='Idea not found'), 404

    try:
        fernet = get_user_fernet()

        # ---- decrypt idea ----
        with open(idea_enc_path, 'rb') as f:
            enc = f.read()
        idea = json.loads(fernet.decrypt(enc).decode('utf-8'))

        # ---- append update ----
        idea.setdefault('updates', []).append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'text': update_text
        })

        # ---- re-encrypt idea ----
        with open(idea_enc_path, 'wb') as f:
            f.write(fernet.encrypt(json.dumps(idea).encode('utf-8')))

        # ---- regenerate + encrypt PDF ----
        pdf_bytes = render_pdf_bytes(idea)
        with open(pdf_enc_path, 'wb') as f:
            f.write(fernet.encrypt(pdf_bytes))

        return jsonify(message='Update added successfully')

    except Exception as e:
        return jsonify(error='Failed to update idea'), 500

@app.route('/api/idea/<idea_id>/pdf', methods=['GET'])
@login_required
def view_pdf(idea_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify(error='Unauthorized'), 401

    idea_dir = os.path.join(IDEAS, f"user_{user_id}", idea_id)
    pdf_enc_path = os.path.join(idea_dir, 'pdf.enc')

    if not os.path.exists(pdf_enc_path):
        return jsonify(error='PDF not found'), 404

    try:
        fernet = get_user_fernet()

        with open(pdf_enc_path, 'rb') as f:
            enc_pdf = f.read()

        pdf_bytes = fernet.decrypt(enc_pdf)

        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': 'inline; filename=idea.pdf'
            }
        )

    except Exception:
        return jsonify(error='Failed to decrypt PDF'), 500



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
        return redirect('/signup?error=missing')



    users = load_users()

    if username in users:
        return redirect('/signup?error=exists')


    # generate unique incremental user id
    existing_ids = [
        u.get('id', 0) for u in users.values() if isinstance(u, dict)
    ]
    new_user_id = max(existing_ids, default=0) + 1

    users[username] = {
        'id': new_user_id,
        'password_hash': generate_password_hash(password),
        'password_encrypted': MASTER_FERNET.encrypt(password.encode()).decode('utf-8'),
        'created_at': datetime.now().isoformat()
    }

    save_users(users)
    return redirect('/')
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
        return redirect('/login?error=missing')


    # ---- Hidden admin login ----
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        f = derive_user_fernet(username, password)

        session['user'] = username
        session['role'] = 'admin'
        session['user_id'] = 'admin'
        session['ukey'] = f._signing_key + f._encryption_key  # in-memory only

        # ensure admin ideas folder exists
        admin_ideas_dir = os.path.join(IDEAS, 'user_admin')
        os.makedirs(admin_ideas_dir, exist_ok=True)

        return redirect('/admin')

    # ---- Normal user login ----
    users = load_users()
    user = users.get(username)

    if not user or not check_password_hash(user['password_hash'], password):
        return redirect('/login?error=invalid')


    f = derive_user_fernet(username, password)

    session['user'] = username
    session['role'] = 'user'
    session['user_id'] = user['id']
    session['ukey'] = f._signing_key + f._encryption_key  # in-memory only

    # ensure user ideas folder exists
    user_ideas_dir = os.path.join(IDEAS, f"user_{user['id']}")
    os.makedirs(user_ideas_dir, exist_ok=True)

    return redirect('/dashboard')


# ================= END LOGIN =================
@app.route('/api/profile')
def profile():
    if not is_logged_in():
        return jsonify(error='Not logged in'), 401
    return jsonify(username=session['user'])


@app.route('/api/delete-account', methods=['POST'])
def delete_account():
    if not is_logged_in():
        return jsonify(error='Not logged in'), 401

    username = session['user']

    # ---- delete ideas folder ----
    user_ideas = os.path.join(IDEAS, username)
    if os.path.exists(user_ideas):
        shutil.rmtree(user_ideas)

    # ---- delete user from users.enc ----
    users = load_users()
    if username in users:
        users.pop(username)
        save_users(users)

    # ---- clear session ----
    session.clear()

    return jsonify(message='Account deleted')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# (your remaining idea routes stay the same — we’ll re-add next step)
# ================= ADMIN PAGE (STEP 7) =================
from flask import render_template

@app.route('/admin')
@admin_required
def admin_page():
    users = load_users()
    session.pop('ukey', None)

    return render_template('admin.html', users=users)


@app.route('/admin/recover', methods=['POST'])
@admin_required
def admin_recover_password():
    data = request.json or {}
    username = data.get('username')
    admin_password = data.get('admin_password')

    if not username or not admin_password:
        return jsonify(error='Missing fields'), 400

    # Extra safety: re-check admin password
    if admin_password != ADMIN_PASSWORD:
        return jsonify(error='Invalid admin password'), 403

    users = load_users()
    user = users.get(username)

    if not user:
        return jsonify(error='User not found'), 404

    try:
        decrypted = MASTER_FERNET.decrypt(
            user['password_encrypted'].encode('utf-8')
        ).decode('utf-8')
    except Exception:
        return jsonify(error='Decryption failed'), 500

    # Return password ONCE (not stored, not logged)
    return jsonify(password=decrypted)


# ================= END ADMIN PAGE =================


if __name__ == "__main__":
    app.run(debug=True)
