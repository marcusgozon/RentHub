import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

# Load secrets from RentHub/.env (git-ignored). Real environment variables, if set,
# take priority over the file. Non-secret defaults (host, port, user, db name) live below.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# HARDCODED SETTINGS: edit the values here and the server works without any
# .env file or terminal setup. A .env file / real environment variable, if you
# ever set one, still takes priority over these.
# WARNING: this file now contains secrets. Do NOT upload it to GitHub or share it.
# ---------------------------------------------------------------------------
HARDCODED = {
    # Gmail account that SENDS the 6-digit codes + its Google App Password
    "GMAIL_USER": "marcusgozon9303@gmail.com",
    "GMAIL_APP_PASSWORD": "lzhr zznj wmtv nebj",
    # MySQL
    "DB_HOST": "localhost",
    "DB_PORT": "3306",
    "DB_USER": "root",
    "DB_PASSWORD": "admin",
    "DB_NAME": "renthub_db",
    # Signs login sessions and hashes codes (keep it fixed so sessions survive restarts)
    "RENTHUB_SECRET_KEY": "c3364d6362a625b705b01b88466c36f7ca28bb145ff0cabfd4dba5c796c0e053",
}

def cfg(name, default=""):
    """Environment/.env value if set, otherwise the hardcoded value above."""
    return os.getenv(name) or HARDCODED.get(name, default)

# Only the frontend/ folder is served to the browser. Backend code, the database
# schema, .env files and the README are never reachable through the web server.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app = Flask(__name__, static_folder=None)

# Set these environment variables before running. Do not commit real passwords.
app.secret_key = cfg("RENTHUB_SECRET_KEY")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("RENTHUB_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

def db_connection():
    return mysql.connector.connect(
        host=cfg("DB_HOST"),
        port=int(cfg("DB_PORT")),
        user=cfg("DB_USER"),
        password=cfg("DB_PASSWORD"),
        database=cfg("DB_NAME"),
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


# ---------------------------------------------------------------------------
# Two-factor authentication (6-digit code sent by Gmail)
# ---------------------------------------------------------------------------
CODE_TTL = timedelta(minutes=10)        # how long a code stays valid
MAX_CODE_ATTEMPTS = 5                   # wrong guesses allowed per code
RESEND_COOLDOWN = timedelta(seconds=30) # minimum wait before asking for a new code

class EmailNotConfigured(Exception):
    pass

def hash_code(user_id, code):
    """Codes are stored as an HMAC so a database leak does not reveal them."""
    return hmac.new(
        app.secret_key.encode(), f"{user_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()

def mask_email(email):
    name, _, domain = email.partition("@")
    return (name[:1] + "***@" + domain) if name else email

def send_code_email(to_email, name, code, purpose="login"):
    """Send the code through Gmail SMTP using an App Password from env variables."""
    sender = cfg("GMAIL_USER").strip()
    app_password = cfg("GMAIL_APP_PASSWORD").replace(" ", "")
    if not sender or not app_password:
        raise EmailNotConfigured()

    msg = EmailMessage()
    msg["Subject"] = f"Your RentHub verification code: {code}"
    msg["From"] = f"RentHub <{sender}>"
    msg["To"] = to_email
    minutes = int(CODE_TTL.total_seconds() // 60)
    if purpose == "signup":
        intro = "Welcome to RentHub! Use this code to finish creating your account."
        outro = "If you did not try to sign up, you can safely ignore this email."
    else:
        intro = "Use this code to finish logging in."
        outro = "If you did not try to log in, ignore this email and consider changing your password."
    msg.set_content(
        f"Hi {name},\n\n{intro}\n\n"
        f"Your RentHub verification code is: {code}\n\n"
        f"It expires in {minutes} minutes. {outro}\n\n- RentHub"
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=15) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)

def issue_login_code(conn, cursor, user):
    """Create a fresh code for the user, store its hash, and email it."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.utcnow()
    cursor.execute("DELETE FROM login_codes WHERE user_id = %s", (user["id"],))
    cursor.execute(
        "INSERT INTO login_codes (user_id, code_hash, expires_at, attempts, created_at) "
        "VALUES (%s, %s, %s, 0, %s)",
        (user["id"], hash_code(user["id"], code), now + CODE_TTL, now),
    )
    conn.commit()
    try:
        send_code_email(user["email"], user["full_name"].split(" ")[0], code)
    except Exception:
        # Do not leave a code behind that nobody received.
        cursor.execute("DELETE FROM login_codes WHERE user_id = %s", (user["id"],))
        conn.commit()
        raise

def issue_signup_code(conn, cursor, email, name, password_hash, role):
    """Email a fresh code and park the signup details until the code is entered.

    The email is sent first, so if Gmail fails nothing is stored and the user can
    simply try again. The real account is only created in /api/verify-signup.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    send_code_email(email, name.split(" ")[0], code, purpose="signup")
    now = datetime.utcnow()
    cursor.execute("DELETE FROM pending_signups WHERE email = %s", (email,))
    cursor.execute(
        "INSERT INTO pending_signups "
        "(email, full_name, password_hash, role, code_hash, expires_at, attempts, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, 0, %s)",
        (email, name, password_hash, role, hash_code("signup:" + email, code), now + CODE_TTL, now),
    )
    conn.commit()

def db_error_response(exc):
    """Explain WHAT went wrong with MySQL instead of one vague message."""
    errno = getattr(exc, "errno", None)
    if errno == 1146:
        msg = "A database table is missing. Restart the server (it creates missing tables) or run database/schema.sql in MySQL Workbench."
    elif errno == 1049:
        msg = "The database renthub_db doesn't exist. Run database/schema.sql in MySQL Workbench."
    elif errno == 1045:
        msg = "MySQL rejected the username or password. Check DB_USER and DB_PASSWORD in your .env file."
    elif errno in (2002, 2003, 2013):
        msg = "Can't reach MySQL. Make sure the MySQL server is running."
    else:
        msg = "Database error. Check the terminal where the server is running for details."
    return jsonify({"error": msg}), 500

def email_error_response(exc):
    if isinstance(exc, EmailNotConfigured):
        return jsonify({"error": "Email sending is not set up. Set GMAIL_USER and GMAIL_APP_PASSWORD, then restart the server."}), 500
    app.logger.exception("Could not send verification email")
    return jsonify({"error": "We couldn't send the verification email. Check the Gmail address and app password."}), 502

def finish_login(user):
    session.clear()
    session.permanent = True
    session.update(
        user_id=user["id"], user_name=user["full_name"],
        user_email=user["email"], user_role=user["role"],
    )

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
        cursor = conn.cursor(dictionary=True)

        # Block duplicate accounts before sending anything.
        if email_exists(cursor, email):
            return jsonify({"error": DUPLICATE_EMAIL_MESSAGE}), 409

        # Housekeeping: forget signups whose code expired over an hour ago.
        cursor.execute(
            "DELETE FROM pending_signups WHERE expires_at < %s",
            (datetime.utcnow() - timedelta(hours=1),),
        )
        # Stop someone from using this form to flood an inbox with codes.
        cursor.execute("SELECT created_at FROM pending_signups WHERE email = %s", (email,))
        row = cursor.fetchone()
        if row:
            wait = RESEND_COOLDOWN - (datetime.utcnow() - row["created_at"])
            if wait > timedelta(0):
                return jsonify({"error": f"Please wait {int(wait.total_seconds()) + 1}s before requesting another code."}), 429

        # Do NOT create the account yet: email a code and wait for it.
        issue_signup_code(conn, cursor, email, name, generate_password_hash(password), role)
        session.clear()
        session["pending_signup_email"] = email
        return jsonify({
            "message": "Verification code sent.",
            "requires_verification": True,
            "email_hint": mask_email(email),
        }), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error during registration")
        return db_error_response(exc)
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

        # Password is correct. Do NOT log in yet: send a code and wait for it.
        issue_login_code(conn, cursor, user)
        session.clear()
        session["pending_user_id"] = user["id"]
        return jsonify({
            "message": "Verification code sent.",
            "requires_2fa": True,
            "email_hint": mask_email(user["email"]),
        }), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error during login")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/verify-2fa")
def verify_2fa():
    user_id = session.get("pending_user_id")
    if not user_id:
        return jsonify({"error": "Your login session expired. Please log in again."}), 401
    code = "".join(ch for ch in str((request.get_json(silent=True) or {}).get("code", "")) if ch.isdigit())
    if len(code) != 6:
        return jsonify({"error": "Enter the 6-digit code."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT code_hash, expires_at, attempts FROM login_codes WHERE user_id = %s", (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "No active code. Request a new one."}), 400
        if row["expires_at"] < datetime.utcnow():
            cursor.execute("DELETE FROM login_codes WHERE user_id = %s", (user_id,))
            conn.commit()
            return jsonify({"error": "That code has expired. Request a new one."}), 400
        if row["attempts"] >= MAX_CODE_ATTEMPTS:
            cursor.execute("DELETE FROM login_codes WHERE user_id = %s", (user_id,))
            conn.commit()
            return jsonify({"error": "Too many wrong attempts. Request a new code."}), 429

        if not hmac.compare_digest(row["code_hash"], hash_code(user_id, code)):
            cursor.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE user_id = %s", (user_id,))
            conn.commit()
            left = MAX_CODE_ATTEMPTS - row["attempts"] - 1
            return jsonify({"error": f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."}), 401

        cursor.execute("DELETE FROM login_codes WHERE user_id = %s", (user_id,))
        cursor.execute("SELECT id, full_name, email, role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        conn.commit()
        if not user:
            session.clear()
            return jsonify({"error": "Account not found."}), 404
        finish_login(user)
        return jsonify({"message": "Logged in.", "user": current_user()}), 200
    except Error as exc:
        app.logger.exception("Database error during 2FA verification")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/resend-2fa")
def resend_2fa():
    user_id = session.get("pending_user_id")
    if not user_id:
        return jsonify({"error": "Your login session expired. Please log in again."}), 401

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT created_at FROM login_codes WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        if row:
            wait = RESEND_COOLDOWN - (datetime.utcnow() - row["created_at"])
            if wait > timedelta(0):
                return jsonify({"error": f"Please wait {int(wait.total_seconds()) + 1}s before requesting another code."}), 429
        cursor.execute("SELECT id, full_name, email FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            session.clear()
            return jsonify({"error": "Account not found."}), 404
        issue_login_code(conn, cursor, user)
        return jsonify({"message": "A new code was sent.", "email_hint": mask_email(user["email"])}), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error while resending 2FA code")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/verify-signup")
def verify_signup():
    email = session.get("pending_signup_email")
    if not email:
        return jsonify({"error": "Your signup session expired. Please sign up again."}), 401
    code = "".join(ch for ch in str((request.get_json(silent=True) or {}).get("code", "")) if ch.isdigit())
    if len(code) != 6:
        return jsonify({"error": "Enter the 6-digit code."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT full_name, password_hash, role, code_hash, expires_at, attempts "
            "FROM pending_signups WHERE email = %s", (email,)
        )
        row = cursor.fetchone()
        if not row:
            session.pop("pending_signup_email", None)
            return jsonify({"error": "Your signup session expired. Please sign up again."}), 401
        # Expired / locked rows are kept on purpose so "Resend code" can reuse them.
        if row["expires_at"] < datetime.utcnow():
            return jsonify({"error": "That code has expired. Request a new one."}), 400
        if row["attempts"] >= MAX_CODE_ATTEMPTS:
            return jsonify({"error": "Too many wrong attempts. Request a new code."}), 429

        if not hmac.compare_digest(row["code_hash"], hash_code("signup:" + email, code)):
            cursor.execute("UPDATE pending_signups SET attempts = attempts + 1 WHERE email = %s", (email,))
            conn.commit()
            left = MAX_CODE_ATTEMPTS - row["attempts"] - 1
            return jsonify({"error": f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."}), 401

        # Code is correct. Re-check the email in case it was registered meanwhile.
        if email_exists(cursor, email):
            cursor.execute("DELETE FROM pending_signups WHERE email = %s", (email,))
            conn.commit()
            session.pop("pending_signup_email", None)
            return jsonify({"error": DUPLICATE_EMAIL_MESSAGE}), 409

        cursor.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (row["full_name"], email, row["password_hash"], row["role"]),
        )
        user_id = cursor.lastrowid
        cursor.execute("DELETE FROM pending_signups WHERE email = %s", (email,))
        conn.commit()
        finish_login({"id": user_id, "full_name": row["full_name"], "email": email, "role": row["role"]})
        return jsonify({"message": "Account created.", "user": current_user()}), 201
    except Error as exc:
        if getattr(exc, "errno", None) == 1062:
            return jsonify({"error": DUPLICATE_EMAIL_MESSAGE}), 409
        app.logger.exception("Database error during signup verification")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/resend-signup")
def resend_signup():
    email = session.get("pending_signup_email")
    if not email:
        return jsonify({"error": "Your signup session expired. Please sign up again."}), 401

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT full_name, password_hash, role, created_at FROM pending_signups WHERE email = %s", (email,)
        )
        row = cursor.fetchone()
        if not row:
            session.pop("pending_signup_email", None)
            return jsonify({"error": "Your signup session expired. Please sign up again."}), 401
        wait = RESEND_COOLDOWN - (datetime.utcnow() - row["created_at"])
        if wait > timedelta(0):
            return jsonify({"error": f"Please wait {int(wait.total_seconds()) + 1}s before requesting another code."}), 429
        issue_signup_code(conn, cursor, email, row["full_name"], row["password_hash"], row["role"])
        return jsonify({"message": "A new code was sent.", "email_hint": mask_email(email)}), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error while resending signup code")
        return db_error_response(exc)
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

def ensure_schema():
    """Create any missing tables by running database/schema.sql (safe to repeat).

    CREATE DATABASE / USE lines are skipped because we are already connected to
    the database. Problems are printed as warnings, they never stop the server.
    """
    schema = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
    try:
        text = "\n".join(l for l in schema.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
        conn = db_connection()
        try:
            cursor = conn.cursor()
            for stmt in (p.strip() for p in text.split(";")):
                if stmt and not stmt.upper().startswith(("CREATE DATABASE", "USE ")):
                    cursor.execute(stmt)
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception as exc:
        print(f"WARNING: could not check/create database tables: {exc}")

# Create any missing tables whenever the app loads, however it is started
# (python app.py, flask run, VS Code run button, ...).
ensure_schema()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
