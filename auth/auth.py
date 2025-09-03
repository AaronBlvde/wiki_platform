from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import jwt, time
from prometheus_client import Gauge, Counter, make_wsgi_app
from werkzeug.middleware.dispatcher import DispatcherMiddleware

app = Flask(__name__)
SECRET = "supersecretkey"

# === Настройка БД ===
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === Модель пользователя ===
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

with app.app_context():
    db.create_all()

# === Метрики Prometheus ===
auth_up = Gauge('auth_service_up', 'Is auth service running')
register_counter = Counter('auth_register_total', 'Total successful registrations')
login_counter = Counter('auth_login_total', 'Total successful logins')

# === Монтируем метрики в Flask под /metrics ===
metrics_app = make_wsgi_app()
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
    '/metrics': metrics_app
})

# === Поток обновления метрик ===
def update_metrics():
    while True:
        auth_up.set(1)
        time.sleep(5)

import threading
threading.Thread(target=update_metrics, daemon=True).start()

# ================== API ==================
@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "user exists"}), 400
    user = User(username=data["username"], password=data["password"])
    db.session.add(user)
    db.session.commit()
    register_counter.inc()
    return jsonify({"status": "ok"})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()
    if user and user.password == data["password"]:
        token = jwt.encode({"user": user.username, "exp": time.time()+3600}, SECRET, algorithm="HS256")
        login_counter.inc()
        return jsonify({"token": token})
    return jsonify({"error": "invalid credentials"}), 401

@app.route("/api/verify", methods=["POST"])
def verify():
    token = request.json.get("token")
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
        return jsonify({"status": "valid"})
    except:
        return jsonify({"status": "invalid"}), 401

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Auth service is running"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
