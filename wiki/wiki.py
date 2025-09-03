from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import threading, time, os
import requests
from prometheus_client import start_http_server, Gauge, Counter

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///wiki.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Catalog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    hidden = db.Column(db.Boolean, default=False)
    pages = db.relationship('Page', backref='catalog', cascade="all, delete-orphan")

class Page(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=True)
    catalog_id = db.Column(db.Integer, db.ForeignKey('catalog.id'))
    hidden = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

wiki_up = Gauge('wiki_service_up', 'Is wiki service running')
article_counter = Counter('wiki_articles_total', 'Total number of created articles')

def metrics_thread():
    start_http_server(8002)
    while True:
        wiki_up.set(1)
        time.sleep(5)

threading.Thread(target=metrics_thread, daemon=True).start()

AUTH_URL = "http://auth:5001/api/verify"

def verify_token(token, retries=10, delay=1):
    """Проверка токена с retry на случай недоступного Auth"""
    if token.startswith("Bearer "):
        token = token[7:]
    for _ in range(retries):
        try:
            resp = requests.post(AUTH_URL, json={"token": token}, timeout=3)
            if resp.status_code == 200:
                return True
        except Exception as e:
            print("Auth service error:", e)
        time.sleep(delay)
    return False

@app.route("/api/pages", methods=["POST"])
def create_page():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "no token"}), 401
    if not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "invalid json"}), 400

    title = data.get("title", "Без названия")
    content = data.get("content", "")
    catalog_id = data.get("catalog_id")
    if catalog_id and not Catalog.query.get(catalog_id):
        return jsonify({"error": "catalog does not exist"}), 400

    try:
        page = Page(title=title, content=content, catalog_id=catalog_id)
        db.session.add(page)
        db.session.commit()
        article_counter.inc()
        return jsonify({"status": "ok", "id": page.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/pages", methods=["GET"])
def list_pages():
    token = request.headers.get("Authorization")
    if not token or not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401
    catalog_id = request.args.get("catalog_id")
    query = Page.query
    if catalog_id:
        query = query.filter_by(catalog_id=catalog_id)
    pages = query.all()
    return jsonify([{
        "id": p.id,
        "title": p.title,
        "content": p.content,
        "catalog_id": p.catalog_id
    } for p in pages])

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Wiki running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
