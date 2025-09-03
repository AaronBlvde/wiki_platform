from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import jwt, time, threading
from prometheus_client import start_http_server, Gauge, Counter
import os

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

def metrics_thread():
    start_http_server(8002)  # Порт для auth
    while True:
        auth_up.set(1)
        time.sleep(5)

# === Запуск метрик только в главном процессе Flask ===
if __name__ == "__main__" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=metrics_thread, daemon=True).start()

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
