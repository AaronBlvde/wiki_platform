from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import threading, time, os
import requests, jwt

from prometheus_client import start_http_server, Gauge, Counter

app = Flask(__name__)

# === Настройка базы данных ===
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///wiki.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === Модели ===
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
    author = db.Column(db.String(80), nullable=False)  # автор статьи

with app.app_context():
    db.create_all()

# === Метрики Prometheus ===
wiki_up = Gauge('wiki_service_up', 'Is wiki service running')
article_counter = Counter('wiki_articles_total', 'Total number of created articles')

def start_metrics():
    """Отдельный поток для метрик"""
    start_http_server(8777, addr="0.0.0.0")  # слушаем на всех интерфейсах
    while True:
        wiki_up.set(1)
        time.sleep(5)

# === Запускаем поток метрик всегда ===
threading.Thread(target=start_metrics, daemon=True).start()

# ================== JWT проверка через auth ==================
AUTH_URL = "http://auth:5001/api/verify"
SECRET = "supersecretkey"  # должен совпадать с auth.py

def decode_token(token):
    """Возвращает имя пользователя из токена или None"""
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        return payload.get("user")
    except Exception as e:
        print("Token decode error:", e)
        return None

def verify_token(token):
    """Проверяет токен через auth-сервис"""
    if not token:
        return False
    if token.startswith("Bearer "):
        token = token.split(" ")[1]
    try:
        resp = requests.post(AUTH_URL, json={"token": token}, timeout=3)
        return resp.status_code == 200
    except Exception as e:
        print("Auth service error:", e)
        return False

# ================== CRUD для страниц ==================
@app.route("/api/pages", methods=["POST"])
def create_page():
    token = request.headers.get("Authorization")
    if not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401

    username = decode_token(token)
    if not username:
        return jsonify({"error": "invalid token"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "invalid json"}), 400

    title = data.get("title", "Без названия")
    content = data.get("content", "")
    catalog_id = data.get("catalog_id")

    if catalog_id:
        catalog = Catalog.query.get(catalog_id)
        if not catalog:
            return jsonify({"error": f"Catalog id {catalog_id} does not exist"}), 400

    try:
        page = Page(title=title, content=content, catalog_id=catalog_id, author=username)
        db.session.add(page)
        db.session.commit()
        article_counter.inc()
        return jsonify({"status": "ok", "id": page.id, "author": page.author})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"DB commit failed: {str(e)}"}), 500

@app.route("/api/pages", methods=["GET"])
def list_pages():
    token = request.headers.get("Authorization")
    if not verify_token(token):
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
        "catalog_id": p.catalog_id,
        "hidden": p.hidden,
        "author": p.author
    } for p in pages])

@app.route("/api/pages/<int:page_id>", methods=["GET"])
def get_page(page_id):
    token = request.headers.get("Authorization")
    if not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401

    page = Page.query.get_or_404(page_id)
    return jsonify({
        "id": page.id,
        "title": page.title,
        "content": page.content,
        "catalog_id": page.catalog_id,
        "author": page.author
    })

@app.route("/api/pages/<int:page_id>", methods=["PUT"])
def edit_page(page_id):
    token = request.headers.get("Authorization")
    if not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401

    username = decode_token(token)
    if not username:
        return jsonify({"error": "invalid token"}), 401

    page = Page.query.get_or_404(page_id)
    if page.author != username:
        return jsonify({"error": "forbidden: only author can edit"}), 403

    data = request.json
    page.title = data.get("title", page.title)
    page.content = data.get("content", page.content)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/api/pages/<int:page_id>", methods=["DELETE"])
def delete_page(page_id):
    token = request.headers.get("Authorization")
    if not verify_token(token):
        return jsonify({"error": "unauthorized"}), 401

    username = decode_token(token)
    if not username:
        return jsonify({"error": "invalid token"}), 401

    page = Page.query.get_or_404(page_id)
    if page.author != username:
        return jsonify({"error": "forbidden: only author can delete"}), 403

    db.session.delete(page)
    db.session.commit()
    return jsonify({"status": "deleted"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Wiki service is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
