import os
from pathlib import Path
from datetime import timedelta

import mysql.connector
from mysql.connector import Error
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

# Only the frontend/ folder is served to the browser. Backend code, the database
# schema, .env files and the README are never reachable through the web server.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app = Flask(__name__, static_folder=None)

# Set these environment variables before running. Do not commit real passwords.
app.secret_key = os.getenv("RENTHUB_SECRET_KEY", "change-this-development-key-before-deployment")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("RENTHUB_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

def db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "renthub_db"),
    )

def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "name": session["user_name"],
        "email": session["user_email"],
        "role": session["user_role"],
    }

def email_exists(cursor, email):
    """Return True if an account with this email is already registered.

    Emails are compared case-insensitively and ignoring surrounding spaces, so
    "Juan@Mail.com " and "juan@mail.com" count as the same address.
    """
    cursor.execute(
        "SELECT 1 FROM users WHERE email = %s LIMIT 1",
        (email.strip().lower(),),
    )
    return cursor.fetchone() is not None

DUPLICATE_EMAIL_MESSAGE = "That email already has an account. Try logging in."

@app.get("/api/me")
def me():
    user = current_user()
    return jsonify({"user": user}), 200

@app.get("/api/check-email")
def check_email():
    """Lets the signup form warn about a taken email before the user submits."""
    email = str(request.args.get("email", "")).strip().lower()
    if not email or len(email) > 255:
        return jsonify({"exists": False}), 200

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        return jsonify({"exists": email_exists(cursor, email)}), 200
    except Error:
        app.logger.exception("Database error while checking email")
        return jsonify({"error": "Database connection failed."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", "tenant")).strip().lower()

    if not name or not email or not password:
        return jsonify({"error": "Please complete all required fields."}), 400
    if len(name) > 100 or len(email) > 255:
        return jsonify({"error": "Name or email is too long."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if role not in ("tenant", "landlord"):
        return jsonify({"error": "Choose tenant or landlord."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()

        # Block duplicate accounts before touching the table.
        if email_exists(cursor, email):
            return jsonify({"error": DUPLICATE_EMAIL_MESSAGE}), 409

        cursor.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (name, email, generate_password_hash(password), role),
        )
        conn.commit()
        user_id = cursor.lastrowid
        session.clear()
        session.permanent = True
        session.update(user_id=user_id, user_name=name, user_email=email, user_role=role)
        return jsonify({"message": "Account created.", "user": current_user()}), 201
    except Error as exc:
        # Safety net: two signups with the same email at the same instant can both
        # pass the check above; MySQL's UNIQUE constraint rejects the second one.
        if getattr(exc, "errno", None) == 1062:
            return jsonify({"error": DUPLICATE_EMAIL_MESSAGE}), 409
        app.logger.exception("Database error during registration")
        return jsonify({"error": "Database connection failed. Check your backend and MySQL settings."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not email or not password:
        return jsonify({"error": "Enter your email and password."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, full_name, email, password_hash, role FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Email or password is incorrect."}), 401

        session.clear()
        session.permanent = True
        session.update(
            user_id=user["id"], user_name=user["full_name"],
            user_email=user["email"], user_role=user["role"]
        )
        return jsonify({"message": "Logged in.", "user": current_user()}), 200
    except Error:
        app.logger.exception("Database error during login")
        return jsonify({"error": "Database connection failed. Check your backend and MySQL settings."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out."}), 200

# Serve the website through Flask so the frontend and API share an origin.
@app.get("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/<path:filename>")
def website_files(filename):
    # Hidden files (.env, .git, ...) are never served. send_from_directory also
    # blocks any attempt to escape the frontend folder (e.g. "../").
    if any(part.startswith(".") for part in filename.split("/")):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(FRONTEND_DIR, filename)

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
