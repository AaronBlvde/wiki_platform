from flask import Flask, render_template, request, redirect, url_for, session
import requests
import os

app = Flask(__name__)
app.secret_key = "supersecret_web_key"

# Автоматически определяем URL сервисов
if os.environ.get("DOCKER") == "1":
    AUTH_URL = "http://auth:5001/api"
    WIKI_URL = "http://wiki:5002/api"
else:
    AUTH_URL = "http://127.0.0.1:5001/api"
    WIKI_URL = "http://127.0.0.1:5002/api"

# ==================== Авторизация ====================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        resp = requests.post(f"{AUTH_URL}/register", json={"username": username, "password": password})
        if resp.status_code == 200:
            return redirect(url_for("login"))
        else:
            return f"Ошибка регистрации: {resp.json()}"
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        resp = requests.post(f"{AUTH_URL}/login", json={"username": username, "password": password})
        if resp.status_code == 200:
            session["token"] = resp.json()["token"]
            return redirect(url_for("dashboard"))
        else:
            error = "Неверный логин или пароль"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop("token", None)
    return redirect(url_for("login"))

# ==================== Дашборд ====================
@app.route("/", methods=["GET", "POST"])
def dashboard():
    token = session.get("token")
    if not token:
        return redirect(url_for("login"))

    search_query = ""
    if request.method == "POST":
        search_query = request.form.get("search", "").lower()

    try:
        resp = requests.get(f"{WIKI_URL}/pages", headers={"Authorization": token}, timeout=5)
        pages = resp.json() if resp.status_code == 200 else []
    except:
        pages = []

    if search_query:
        pages = [p for p in pages if search_query in p["title"].lower() or search_query in (p["content"] or "").lower()]

    return render_template("dashboard.html", pages=pages, search_query=search_query)

# ==================== Создание статьи ====================
@app.route("/create_page", methods=["POST"])
def create_page():
    token = session.get("token")
    if not token:
        return redirect(url_for("login"))

    title = request.form.get("title")
    content = request.form.get("content")
    if not title.strip():
        return redirect(url_for("dashboard"))

    try:
        requests.post(
            f"{WIKI_URL}/pages",
            json={"title": title, "content": content},
            headers={"Authorization": f"Bearer {token}"},
            timeout=5

        )
    except Exception as e:
        print("Error creating page:", e)

    return redirect(url_for("dashboard"))

# ==================== Удаление статьи ====================
@app.route("/delete_page/<int:page_id>")
def delete_page(page_id):
    token = session.get("token")
    if not token:
        return redirect(url_for("login"))
    try:
        requests.delete(f"{WIKI_URL}/pages/{page_id}", headers={"Authorization": token}, timeout=5)
    except Exception as e:
        print("Error deleting page:", e)
    return redirect(url_for("dashboard"))

# ==================== Редактирование статьи ====================
@app.route("/edit_page/<int:page_id>", methods=["GET", "POST"])
def edit_page(page_id):
    token = session.get("token")
    if not token:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        if title.strip():
            try:
                requests.put(
                    f"{WIKI_URL}/pages/{page_id}",
                    json={"title": title, "content": content},
                    headers={"Authorization": token},
                    timeout=5
                )
            except Exception as e:
                print("Error updating page:", e)
        return redirect(url_for("dashboard"))

    try:
        resp = requests.get(f"{WIKI_URL}/pages/{page_id}", headers={"Authorization": token}, timeout=5)
        page = resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print("Error fetching page:", e)
        page = None

    if not page:
        return redirect(url_for("dashboard"))

    return render_template("edit_page.html", page=page)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
