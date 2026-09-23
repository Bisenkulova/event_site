"""Учебный сайт агентства праздников без CMS, на Flask и SQLite."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from content import ARTICLES, CATEGORIES

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = Path(os.environ.get("EVENT_SITE_INSTANCE", BASE_DIR / "instance"))
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = INSTANCE_DIR / "events.sqlite3"
SECRET_FILE = INSTANCE_DIR / "secret.key"
if os.environ.get("EVENT_SITE_SECRET"):
    secret_key = os.environ["EVENT_SITE_SECRET"]
else:
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
        SECRET_FILE.chmod(0o600)
    secret_key = SECRET_FILE.read_text(encoding="utf-8").strip()

app = Flask(__name__)
app.config.update(SECRET_KEY=secret_key, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax")


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL
            CHECK(role IN ('customer','editor')));
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY, category TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, lead TEXT NOT NULL, body1 TEXT NOT NULL,
            body2 TEXT NOT NULL, updated_at TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL, body TEXT NOT NULL, reply TEXT,
            created_at TEXT NOT NULL, answered_at TEXT);
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL);
        """)
        if db.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).date().isoformat()
            db.executemany("""INSERT INTO articles
                (category,slug,title,lead,body1,body2,updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                [(cat, slug, title, lead, body1, body2, now)
                 for cat, slug, title, lead, body1, body2 in ARTICLES])
        if db.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 0:
            db.executemany("INSERT INTO news (title,body) VALUES (?,?)", [
                ("Три направления программы", "Опубликованы материалы о детских, семейных и корпоративных событиях."),
                ("Сценарии подготовки", "В каждом направлении доступны пять статей с практическими вопросами к организатору."),
                ("Доступная версия", "Включается версия с усиленным контрастом и увеличенным шрифтом."),
                ("Обратная связь", "После регистрации посетитель может отправить запрос и прочитать ответ редактора в личном кабинете."),
            ])


init_db()


@app.before_request
def load_user():
    g.db = connect()
    g.user = None
    if "user_id" in session:
        g.user = g.db.execute("SELECT id,username,role FROM users WHERE id=?",
                              (session["user_id"],)).fetchone()
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    if request.method == "POST":
        token = request.form.get("csrf", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Недействительный защитный код формы")


@app.teardown_request
def close_connection(exc):
    if hasattr(g, "db"):
        g.db.close()


@app.context_processor
def template_context():
    return {"categories": CATEGORIES, "csrf_token": session.get("csrf", "")}


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Войдите, чтобы продолжить.")
                return redirect(url_for("login"))
            if role and g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.get("/")
def home():
    news = g.db.execute("SELECT * FROM news ORDER BY id DESC LIMIT 4").fetchall()
    recent = g.db.execute("SELECT * FROM articles WHERE published=1 ORDER BY id DESC LIMIT 3").fetchall()
    return render_template("home.html", news=news, recent=recent)


@app.get("/services")
def services():
    return render_template("services.html")


@app.get("/articles")
def article_index():
    category = request.args.get("category", "")
    if category and category not in CATEGORIES:
        abort(404)
    if category:
        items = g.db.execute("SELECT * FROM articles WHERE published=1 AND category=? ORDER BY id",
                             (category,)).fetchall()
    else:
        items = g.db.execute("SELECT * FROM articles WHERE published=1 ORDER BY category,id").fetchall()
    return render_template("articles.html", items=items, selected=category)


@app.get("/articles/<slug>")
def article(slug):
    item = g.db.execute("SELECT * FROM articles WHERE slug=? AND published=1", (slug,)).fetchone()
    if item is None:
        abort(404)
    related = g.db.execute("SELECT * FROM articles WHERE category=? AND id<>? AND published=1 LIMIT 3",
                           (item["category"], item["id"])).fetchall()
    return render_template("article.html", item=item, related=related)


@app.get("/portfolio")
def portfolio():
    return render_template("portfolio.html")


@app.get("/estimate")
def estimate():
    return render_template("estimate.html")


@app.get("/about")
def about():
    return render_template("about.html")


@app.get("/contacts")
def contacts():
    return render_template("contacts.html")


@app.get("/search")
def search():
    term = request.args.get("q", "").strip()[:80]
    items = []
    if term:
        pattern = "%" + term.replace("%", "\\%").replace("_", "\\_") + "%"
        items = g.db.execute("""SELECT * FROM articles WHERE published=1 AND
          (title LIKE ? ESCAPE '\\' OR lead LIKE ? ESCAPE '\\' OR body1 LIKE ? ESCAPE '\\')
          ORDER BY category,id""", (pattern, pattern, pattern)).fetchall()
    return render_template("search.html", term=term, items=items)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        if not (3 <= len(username) <= 32 and username.replace("_", "").isalnum()):
            flash("Логин: 3–32 буквы, цифры и знак подчёркивания.")
        elif len(password) < 12:
            flash("Пароль должен содержать минимум 12 символов.")
        else:
            try:
                with connect() as db:
                    db.execute("INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
                               (username, generate_password_hash(password), "customer"))
                flash("Учётная запись создана. Теперь войдите.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Такой логин уже занят.")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = g.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf"] = secrets.token_urlsafe(24)
            return redirect(url_for("editor" if user["role"] == "editor" else "account"))
        flash("Неверный логин или пароль.")
    return render_template("auth.html", mode="login")


@app.post("/logout")
@login_required()
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/account")
@login_required()
def account():
    messages = g.db.execute("SELECT * FROM messages WHERE user_id=? ORDER BY id DESC",
                            (g.user["id"],)).fetchall()
    return render_template("account.html", messages=messages)


@app.post("/messages")
@login_required()
def new_message():
    subject = request.form.get("subject", "").strip()[:100]
    body = request.form.get("body", "").strip()[:2000]
    if len(subject) < 4 or len(body) < 15:
        flash("Укажите тему от 4 знаков и текст от 15 знаков.")
        return redirect(url_for("contacts"))
    with connect() as db:
        db.execute("INSERT INTO messages (user_id,subject,body,created_at) VALUES (?,?,?,?)",
                   (g.user["id"], subject, body, datetime.now(timezone.utc).isoformat(timespec="minutes")))
    flash("Сообщение сохранено в личном кабинете.")
    return redirect(url_for("account"))


@app.get("/editor")
@login_required("editor")
def editor():
    items = g.db.execute("SELECT * FROM articles ORDER BY category,id").fetchall()
    messages = g.db.execute("""SELECT m.*,u.username FROM messages m JOIN users u ON u.id=m.user_id
                            ORDER BY m.id DESC""").fetchall()
    return render_template("editor.html", items=items, messages=messages)


@app.route("/editor/articles/<int:article_id>", methods=["GET", "POST"])
@login_required("editor")
def edit_article(article_id):
    item = g.db.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if item is None:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:150]
        lead = request.form.get("lead", "").strip()[:350]
        body1 = request.form.get("body1", "").strip()[:3000]
        body2 = request.form.get("body2", "").strip()[:3000]
        published = 1 if request.form.get("published") == "1" else 0
        if min(map(len, (title, lead, body1, body2))) < 15:
            flash("Заполните заголовок, анонс и оба содержательных блока.")
        else:
            with connect() as db:
                db.execute("""UPDATE articles SET title=?,lead=?,body1=?,body2=?,published=?,updated_at=?
                               WHERE id=?""", (title, lead, body1, body2, published,
                                               datetime.now(timezone.utc).date().isoformat(), article_id))
            flash("Материал обновлён.")
            return redirect(url_for("editor"))
    return render_template("edit.html", item=item)


@app.post("/editor/messages/<int:message_id>")
@login_required("editor")
def reply(message_id):
    body = request.form.get("reply", "").strip()[:2000]
    if len(body) < 4:
        flash("Ответ слишком короткий.")
    else:
        with connect() as db:
            result = db.execute("UPDATE messages SET reply=?,answered_at=? WHERE id=?",
                                (body, datetime.now(timezone.utc).isoformat(timespec="minutes"), message_id))
            if result.rowcount == 0:
                abort(404)
        flash("Ответ сохранён и виден автору сообщения.")
    return redirect(url_for("editor"))


@app.get("/sitemap")
def sitemap():
    return render_template("sitemap.html")


@app.errorhandler(404)
def missing(exc):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(exc):
    return render_template("403.html"), 403


if __name__ == "__main__":
    app.run(debug=False)
