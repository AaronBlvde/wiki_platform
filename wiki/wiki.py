from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import threading, time, os
import requests
from sqlalchemy import text
from prometheus_client import start_http_server, Gauge, Counter

app = Flask(__name__)

# === DB ===
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///wiki.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === Models ===
class Catalog(db.Model):
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(100), nullable=False)
    hidden = db.Column(db.Boolean, default=False)
    pages  = db.relationship('Page', backref='catalog', cascade="all, delete-orphan")

class Page(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(150), nullable=False)
    content    = db.Column(db.Text, nullable=True)
    catalog_id = db.Column(db.Integer, db.ForeignKey('catalog.id'))
    hidden     = db.Column(db.Boolean, default=False)
    # НОВОЕ: автор статьи
    author     = db.Column(db.String(80), nullable=True)  # оставим nullable=True для мягкой миграции

with app.app_context():
    db.create_all()

    # Мягкая миграция: добавим колонку author, если её нет (SQLite)
    with db.engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(page);")).fetchall()]
        if "author" not in cols:
            conn.execute(text("ALTER TABLE page ADD COLUMN author VARCHAR(80)"))
            conn.execute(text("UPDATE page SET author = 'unknown' WHERE author IS NULL"))

# === Metrics ===
wiki_up          = Gauge('wiki_service_up', 'Is wiki service running')
article_counter  = Counter('wiki_articles_total', 'Total number of created articles')
delete_denied_ct = Counter('wiki_delete_denied_total', 'Delete denied (not owner)')

def start_metrics():
    try:
        start_http_server(8777, addr="0.0.0.0")
    except OSError:
        pass
    while True:
        wiki_up.set(1)
        time.sleep(5)

threading.Thread(target=start_metrics, daemon=True).start()

# === Auth verify ===
AUTH_URL = "http://auth:5001/api/verify"

def verify_token_and_get_login(token: str):
    """
    Возвращает логин (str) если токен валидный, иначе None.
    Поддерживает заголовок Bearer и «сырой» токен.
    """
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    try:
        resp = requests.post(AUTH_URL, json={"token": token}, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "valid":
                return data.get("login")
        return None
    except Exception as e:
        print("Auth service error:", e)
        return None

# === CRUD ===
@app.route("/api/pages", methods=["POST"])
def create_page():
    token = request.headers.get("Authorization")
    login = verify_token_and_get_login(token)
    if not login:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}
    title = (data.get("title") or "").strip() or "Без названия"
    content = data.get("content", "")
    catalog_id = data.get("catalog_id")

    if catalog_id:
        catalog = Catalog.query.get(catalog_id)
        if not catalog:
            return jsonify({"error": f"Catalog id {catalog_id} does not exist"}), 400

    try:
        page = Page(title=title, content=content, catalog_id=catalog_id, author=login)
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
    login = verify_token_and_get_login(token)
    if not login:
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
        "author": p.author or "unknown"
    } for p in pages])

@app.route("/api/pages/<int:page_id>", methods=["GET"])
def get_page(page_id):
    token = request.headers.get("Authorization")
    login = verify_token_and_get_login(token)
    if not login:
        return jsonify({"error": "unauthorized"}), 401

    page = Page.query.get_or_404(page_id)
    return jsonify({
        "id": page.id,
        "title": page.title,
        "content": page.content,
        "catalog_id": page.catalog_id,
        "author": page.author or "unknown"
    })

@app.route("/api/pages/<int:page_id>", methods=["PUT"])
def edit_page(page_id):
    token = request.headers.get("Authorization")
    login = verify_token_and_get_login(token)
    if not login:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}
    page = Page.query.get_or_404(page_id)

    # при желании можно ограничить редактирование только автору:
    # if (page.author or "unknown") != login: return jsonify({"error": "forbidden"}), 403

    page.title   = (data.get("title") or page.title)
    page.content = (data.get("content") or page.content)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/api/pages/<int:page_id>", methods=["DELETE"])
def delete_page(page_id):
    token = request.headers.get("Authorization")
    login = verify_token_and_get_login(token)
    if not login:
        return jsonify({"error": "unauthorized"}), 401

    page = Page.query.get_or_404(page_id)
    if (page.author or "unknown") != login:
        delete_denied_ct.inc()
        return jsonify({"error": "forbidden: not your post"}), 403

    db.session.delete(page)
    db.session.commit()
    return jsonify({"status": "deleted"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Wiki service is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
