from flask import Flask, send_from_directory, request, jsonify, Response
from datetime import datetime
import os, json, shutil
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

app = Flask(__name__, static_folder='static')
BASE = os.path.dirname(os.path.abspath(__file__))
IDEAS = os.path.join(BASE,'ideas')
STATIC = os.path.join(BASE,'static')
os.makedirs(IDEAS, exist_ok=True)

def clean(s): return ''.join(c for c in s if c.isalnum() or c in ' _-').strip()

def unique(name):
    n=name; i=1
    while os.path.exists(os.path.join(IDEAS,n)):
        i+=1; n=f"{name} ({i})"
    return n

@app.route('/')
def home(): return send_from_directory(STATIC,'index.html')

@app.route('/dashboard')
def dash(): return send_from_directory(STATIC,'dashboard.html')

@app.route('/api/save-idea', methods=['POST'])
def save():
    d = request.json or {}
    if not d.get('title'):
        return jsonify(error='Title required'), 400

    folder = unique(clean(d['title']))
    path = os.path.join(IDEAS, folder)
    os.makedirs(path)

    d['dateCreated'] = d.get('dateCreated') or datetime.now().strftime('%Y-%m-%d')
    d['generatedAt'] = datetime.now().strftime('%d %B %Y %H:%M')
    d.setdefault('updates', [])

    json_path = os.path.join(path, 'idea.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2)

    render_pdf(folder)

    return jsonify(message='Idea saved', folder=folder)

@app.route('/api/dashboard/ideas')
def list_ideas():
    out=[]
    for f in os.listdir(IDEAS):
        p=os.path.join(IDEAS,f,'idea.json')
        if os.path.exists(p):
            d=json.load(open(p))
            out.append({'folder':f,'title':d.get('title'),'dateCreated':d.get('dateCreated'),'summary':d.get('summary'),'updatesCount':len(d.get('updates',[]))})
    return jsonify(out)

@app.route('/api/idea/<folder>')
def get(folder):
    json_path = os.path.join(IDEAS, clean(folder), 'idea.json')
    if not os.path.exists(json_path):
        return jsonify(error='Not found'), 404
    with open(json_path, encoding='utf-8') as f:
        return Response(json.dumps(json.load(f), indent=2), mimetype='application/json')

@app.route('/api/add-update', methods=['POST'])
def add():
    d = request.json or {}
    folder = clean(d.get('ideaTitle', ''))
    path = os.path.join(IDEAS, folder)
    json_path = os.path.join(path, 'idea.json')

    if not os.path.exists(json_path):
        return jsonify(error='Idea not found'), 404

    idea = json.load(open(json_path, encoding='utf-8'))

    idea.setdefault('updates', []).append({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'text': d.get('updateText', '')
    })

    idea['generatedAt'] = datetime.now().strftime('%d %B %Y %H:%M')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(idea, f, indent=2)

    render_pdf(folder)

    return jsonify(message='Update added')

@app.route('/api/idea/<folder>', methods=['DELETE'])
def delete(folder):
    path = os.path.join(IDEAS, clean(folder))
    if not os.path.exists(path):
        return jsonify(error='Not found'), 404
    shutil.rmtree(path)
    return jsonify(message='Deleted')

def render_pdf(folder):
    json_path = os.path.join(IDEAS, folder, 'idea.json')
    pdf_path = os.path.join(IDEAS, folder, 'idea.pdf')

    if not os.path.exists(json_path):
        return

    data = json.load(open(json_path, encoding='utf-8'))

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
        f"Generated on {data.get('generatedAt')}",
        styles['Italic']
    ))

    doc.build(story)


@app.route('/api/idea/<folder>/pdf')
def view_pdf(folder):
    pdf = os.path.join(IDEAS, clean(folder), 'idea.pdf')
    if not os.path.exists(pdf):
        render_pdf(clean(folder))
    return send_from_directory(os.path.dirname(pdf), 'idea.pdf')


if __name__ == '__main__':
    app.run(debug=True)
