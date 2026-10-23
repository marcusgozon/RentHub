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
from flask import Flask, Response, jsonify, request, session, send_from_directory
import re as _re
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

# Profile photos are stored in the database (users.avatar_data), not on disk.
# This folder is only read once to move any older photos into the database.
LEGACY_AVATAR_DIR = Path(__file__).resolve().parent.parent / "uploads" / "avatars"
MIME_BY_EXT = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
# Only real images are accepted: we check the file's first bytes, not just its name.
IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"RIFF", "webp"),  # also checked for "WEBP" below
)

# Set these environment variables before running. Do not commit real passwords.
app.secret_key = cfg("RENTHUB_SECRET_KEY")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("RENTHUB_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=13 * 1024 * 1024,  # reject oversized uploads early (each photo is still limited to 2 MB)
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
    elif purpose == "reset":
        intro = "Use this code to reset your password."
        outro = "If you did not request a password reset, you can safely ignore this email."
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


def issue_password_reset_code(conn, cursor, user):
    """Create and email a 6-digit code to reset the user's password."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.utcnow()
    cursor.execute("DELETE FROM password_resets WHERE email = %s", (user["email"],))
    cursor.execute(
        "INSERT INTO password_resets (email, code_hash, expires_at, attempts, created_at) "
        "VALUES (%s, %s, %s, 0, %s)",
        (user["email"], hash_code("reset:" + user["email"], code), now + CODE_TTL, now),
    )
    conn.commit()
    try:
        send_code_email(user["email"], user["full_name"].split(" ")[0], code, purpose="reset")
    except Exception:
        cursor.execute("DELETE FROM password_resets WHERE email = %s", (user["email"],))
        conn.commit()
        raise


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

@app.post("/api/forgot-password")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return jsonify({"error": "Enter your email address."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, full_name, email FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        if user:
            cursor.execute("SELECT created_at FROM password_resets WHERE email = %s", (email,))
            row = cursor.fetchone()
            if row:
                wait = RESEND_COOLDOWN - (datetime.utcnow() - row["created_at"])
                if wait > timedelta(0):
                    return jsonify({"error": f"Please wait {int(wait.total_seconds()) + 1}s before requesting another code."}), 429
            issue_password_reset_code(conn, cursor, user)
            session.clear()
            session["pending_reset_email"] = email
            return jsonify({
                "message": "If that account exists, a password reset code has been sent.",
                "email_hint": mask_email(email),
                "requires_reset_verification": True,
            }), 200

        return jsonify({
            "message": "If that account exists, a password reset code has been sent.",
            "email_hint": mask_email(email),
        }), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error while creating reset code")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/verify-reset-code")
def verify_reset_code():
    email = session.get("pending_reset_email")
    if not email:
        return jsonify({"error": "Your reset session expired. Please request a new code."}), 401
    code = "".join(ch for ch in str((request.get_json(silent=True) or {}).get("code", "")) if ch.isdigit())
    if len(code) != 6:
        return jsonify({"error": "Enter the 6-digit code."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT code_hash, expires_at, attempts FROM password_resets WHERE email = %s",
            (email,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "No active reset code. Request a new one."}), 400
        if row["expires_at"] < datetime.utcnow():
            cursor.execute("DELETE FROM password_resets WHERE email = %s", (email,))
            conn.commit()
            return jsonify({"error": "That code has expired. Request a new one."}), 400
        if row["attempts"] >= MAX_CODE_ATTEMPTS:
            cursor.execute("DELETE FROM password_resets WHERE email = %s", (email,))
            conn.commit()
            return jsonify({"error": "Too many wrong attempts. Request a new code."}), 429

        if not hmac.compare_digest(row["code_hash"], hash_code("reset:" + email, code)):
            cursor.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE email = %s", (email,))
            conn.commit()
            left = MAX_CODE_ATTEMPTS - row["attempts"] - 1
            return jsonify({"error": f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."}), 401

        cursor.execute("DELETE FROM password_resets WHERE email = %s", (email,))
        conn.commit()
        session["reset_verified_email"] = email
        session.pop("pending_reset_email", None)
        return jsonify({"message": "Code verified. Choose a new password."}), 200
    except Error as exc:
        app.logger.exception("Database error during password reset verification")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/resend-reset-code")
def resend_reset_code():
    email = session.get("pending_reset_email")
    if not email:
        return jsonify({"error": "Your reset session expired. Please request a new code."}), 401

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT created_at FROM password_resets WHERE email = %s", (email,))
        row = cursor.fetchone()
        if row:
            wait = RESEND_COOLDOWN - (datetime.utcnow() - row["created_at"])
            if wait > timedelta(0):
                return jsonify({"error": f"Please wait {int(wait.total_seconds()) + 1}s before requesting another code."}), 429
        cursor.execute("SELECT id, full_name, email FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            session.clear()
            return jsonify({"error": "Account not found."}), 404
        issue_password_reset_code(conn, cursor, user)
        return jsonify({"message": "A new reset code was sent.", "email_hint": mask_email(user["email"])}), 200
    except (EmailNotConfigured, smtplib.SMTPException, OSError) as exc:
        return email_error_response(exc)
    except Error as exc:
        app.logger.exception("Database error while resending password reset code")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/reset-password")
def reset_password():
    email = session.get("reset_verified_email")
    if not email:
        return jsonify({"error": "Your reset session expired. Please request a new code."}), 401
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    conn = None
    cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (generate_password_hash(password), email))
        cursor.execute("DELETE FROM password_resets WHERE email = %s", (email,))
        cursor.execute("SELECT id, full_name, email, role FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        conn.commit()
        if not user:
            session.clear()
            return jsonify({"error": "Account not found."}), 404
        finish_login(user)
        session.pop("reset_verified_email", None)
        return jsonify({"message": "Password updated. You are now logged in.", "user": current_user()}), 200
    except Error as exc:
        app.logger.exception("Database error while resetting password")
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

# ---------------------------------------------------------------------------
# Profile: view/update mobile number and profile photo
# ---------------------------------------------------------------------------
def normalize_ph_mobile(raw):
    """Return a Philippine mobile number as 09XXXXXXXXX, "" if blank, or None if invalid."""
    digits = _re.sub(r"[\s\-()]", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("+63"):
        digits = "0" + digits[3:]
    elif digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits if _re.fullmatch(r"09\d{9}", digits) else None

def avatar_url(token):
    # `avatar` holds a random token. It is the public URL key and changes with every new photo.
    return f"/api/avatar/{token}" if token else None

def detect_image_ext(data):
    for sig, ext in IMAGE_SIGNATURES:
        if data.startswith(sig):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return None

def profile_json(row):
    return {
        "name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "phone": row.get("phone") or "",
        "avatar": avatar_url(row.get("avatar")),
        "member_since": row["created_at"].strftime("%Y-%m-%d") if row.get("created_at") else None,
    }

def fetch_profile(cursor, user_id):
    cursor.execute(
        "SELECT full_name, email, role, phone, avatar, created_at FROM users WHERE id = %s", (user_id,)
    )
    return cursor.fetchone()

@app.get("/api/profile")
def get_profile():
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        row = fetch_profile(cursor, user["id"])
        if not row:
            session.clear()
            return jsonify({"error": "Account not found."}), 404
        return jsonify({"profile": profile_json(row)}), 200
    except Error as exc:
        app.logger.exception("Database error while loading profile")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.post("/api/profile")
def update_profile():
    """Update full name, mobile number, and/or profile photo using multipart/form-data."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    full_name = None
    if "full_name" in request.form:
        full_name = request.form["full_name"].strip()
        if not full_name or len(full_name) > 100:
            return jsonify({"error": "Enter a full name between 1 and 100 characters."}), 400

    phone = None
    if "phone" in request.form:
        phone = normalize_ph_mobile(request.form["phone"])
        if phone is None:
            return jsonify({"error": "Enter a valid mobile number, like 09171234567 or +639171234567."}), 400

    new_token = new_mime = None
    upload = request.files.get("photo")
    if upload and upload.filename:
        data = upload.read(MAX_AVATAR_BYTES + 1)
        if len(data) > MAX_AVATAR_BYTES:
            return jsonify({"error": "That photo is too big. Please choose one under 2 MB."}), 413
        ext = detect_image_ext(data)
        if not ext:
            return jsonify({"error": "Please upload a JPG, PNG or WEBP image."}), 400
        new_token = secrets.token_hex(16)
        new_mime = MIME_BY_EXT[ext]

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        row = fetch_profile(cursor, user["id"])
        if not row:
            session.clear()
            return jsonify({"error": "Account not found."}), 404

        if full_name is not None:
            cursor.execute("UPDATE users SET full_name = %s WHERE id = %s", (full_name, user["id"]))
        if phone is not None:
            cursor.execute("UPDATE users SET phone = %s WHERE id = %s", (phone or None, user["id"]))
        if new_token:
            # The image bytes go straight into the database; replacing a photo overwrites the old one.
            cursor.execute(
                "UPDATE users SET avatar = %s, avatar_data = %s, avatar_mime = %s WHERE id = %s",
                (new_token, data, new_mime, user["id"]),
            )
        elif request.form.get("remove_photo") == "1":
            cursor.execute(
                "UPDATE users SET avatar = NULL, avatar_data = NULL, avatar_mime = NULL WHERE id = %s",
                (user["id"],),
            )
        conn.commit()
        if full_name is not None:
            session["user_name"] = full_name

        row = fetch_profile(cursor, user["id"])
        return jsonify({"message": "Profile updated.", "profile": profile_json(row)}), 200
    except Error as exc:
        app.logger.exception("Database error while updating profile")
        return db_error_response(exc)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "That file is too big. Please choose a photo under 2 MB."}), 413

@app.get("/api/avatar/<token>")
def avatar_file(token):
    """Serve a profile photo from the database. The token is random, so URLs can't be guessed."""
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT avatar_data, avatar_mime FROM users WHERE avatar = %s", (token,))
        row = cursor.fetchone()
    except Error:
        app.logger.exception("Database error while loading avatar")
        return jsonify({"error": "Could not load the photo."}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    if not row or not row[0]:
        return jsonify({"error": "Not found"}), 404
    resp = Response(bytes(row[0]), mimetype=row[1] or "application/octet-stream")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # URL changes with each new photo
    return resp

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out."}), 200

# ---------------------------------------------------------------------------
# Listings, listing photos and tenant reviews
# ---------------------------------------------------------------------------
LISTING_TYPES = ("Studio", "Condo", "Apartment", "House", "Bedspace")
MAX_LISTING_PHOTOS = 6

def listing_image_url(token):
    return f"/api/listing-image/{token}" if token else None

def whole_or_float(value):
    number = float(value)
    return int(number) if number.is_integer() else number

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None

def listing_json(row, tokens):
    """Public shape of a listing. Never includes the landlord's email, phone or password."""
    urls = [listing_image_url(t) for t in tokens]
    return {
        "id": row["id"],
        "title": row["title"],
        "location": row["location"],
        "type": row["type"],
        "price": whole_or_float(row["price"]),
        "beds": row["beds"],
        "baths": row["baths"],
        "description": row.get("description") or "",
        "status": row["status"],
        "available": row["status"] == "available",
        "image": urls[0] if urls else None,
        "images": urls,
        "created_at": iso(row.get("created_at")),
        "landlord": {
            "name": row.get("landlord_name"),
            "avatar": avatar_url(row.get("landlord_avatar")),
            "since": row["landlord_since"].strftime("%Y-%m-%d") if row.get("landlord_since") else None,
        },
    }

LISTING_SELECT = (
    "SELECT l.id, l.landlord_id, l.title, l.location, l.type, l.price, l.beds, l.baths, "
    "l.description, l.status, l.created_at, "
    "u.full_name AS landlord_name, u.avatar AS landlord_avatar, u.created_at AS landlord_since "
    "FROM listings l JOIN users u ON u.id = l.landlord_id "
)

def fetch_listings(cursor, where="", params=()):
    """Run the listing query and attach each listing's photo tokens (in display order)."""
    cursor.execute(LISTING_SELECT + where + " ORDER BY l.created_at DESC, l.id DESC", params)
    rows = cursor.fetchall()
    tokens = {}
    if rows:
        marks = ",".join(["%s"] * len(rows))
        cursor.execute(
            f"SELECT listing_id, token FROM listing_images WHERE listing_id IN ({marks}) "
            "ORDER BY listing_id, sort_order, id",
            tuple(r["id"] for r in rows),
        )
        for row in cursor.fetchall():
            tokens.setdefault(row["listing_id"], []).append(row["token"])
    return [listing_json(r, tokens.get(r["id"], [])) for r in rows]

def close_db(conn, cursor):
    if cursor:
        cursor.close()
    if conn and conn.is_connected():
        conn.close()

def int_in_range(raw, low, high):
    """Return raw as an int within [low, high], or None."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None

@app.get("/api/listings")
def list_listings():
    """Public: every listing, newest first. (There is no approval step in this project yet.)"""
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        return jsonify({"listings": fetch_listings(cursor)}), 200
    except Error as exc:
        app.logger.exception("Database error while listing homes")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/listings/<int:listing_id>")
def get_listing(listing_id):
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        found = fetch_listings(cursor, "WHERE l.id = %s", (listing_id,))
        if not found:
            return jsonify({"error": "Listing not found."}), 404
        return jsonify({"listing": found[0]}), 200
    except Error as exc:
        app.logger.exception("Database error while loading a listing")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/my-listings")
def my_listings():
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] != "landlord":
        return jsonify({"error": "Only landlords have listings."}), 403
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        return jsonify({"listings": fetch_listings(cursor, "WHERE l.landlord_id = %s", (user["id"],))}), 200
    except Error as exc:
        app.logger.exception("Database error while loading my listings")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/listings")
def create_listing():
    """Landlords only. multipart/form-data: title, location, type, price, beds, baths,
    description (optional), photo (one or more image files, up to 6)."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] != "landlord":
        return jsonify({"error": "Only landlords can post homes."}), 403

    form = request.form
    title = (form.get("title") or "").strip()
    location = (form.get("location") or "").strip()
    ltype = (form.get("type") or "").strip()
    description = (form.get("description") or "").strip()
    try:
        price = round(float(form.get("price", "")), 2)
    except ValueError:
        price = 0
    beds = int_in_range(form.get("beds", 0), 0, 50)
    baths = int_in_range(form.get("baths", 1), 1, 50)

    if not title or len(title) > 120:
        return jsonify({"error": "Add a title (up to 120 characters)."}), 400
    if not location or len(location) > 160:
        return jsonify({"error": "Add a location (up to 160 characters)."}), 400
    if ltype not in LISTING_TYPES:
        return jsonify({"error": "Choose a valid property type."}), 400
    if not (0 < price <= 99999999):
        return jsonify({"error": "Enter a monthly price above 0."}), 400
    if beds is None or baths is None:
        return jsonify({"error": "Beds must be 0 or more and baths at least 1."}), 400
    if len(description) > 5000:
        return jsonify({"error": "The description is too long (5000 characters max)."}), 400

    photos = []
    uploads = [f for f in request.files.getlist("photo") + request.files.getlist("photos") if f and f.filename]
    if len(uploads) > MAX_LISTING_PHOTOS:
        return jsonify({"error": f"You can upload up to {MAX_LISTING_PHOTOS} photos."}), 400
    for upload in uploads:
        data = upload.read(MAX_AVATAR_BYTES + 1)
        if len(data) > MAX_AVATAR_BYTES:
            return jsonify({"error": "A photo is too big. Please choose ones under 2 MB."}), 413
        ext = detect_image_ext(data)
        if not ext:
            return jsonify({"error": "Please upload JPG, PNG or WEBP images."}), 400
        photos.append((secrets.token_hex(16), data, MIME_BY_EXT[ext]))

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        # Double-click / double-submit guard: the same landlord can't post the same home twice in 30 seconds.
        cursor.execute(
            "SELECT id FROM listings WHERE landlord_id = %s AND title = %s AND location = %s AND price = %s "
            "AND created_at > (NOW() - INTERVAL 30 SECOND) LIMIT 1",
            (user["id"], title, location, price),
        )
        if cursor.fetchone():
            return jsonify({"error": "You just posted this home. Check Browse or Your listings."}), 409
        cursor.execute(
            "INSERT INTO listings (landlord_id, title, location, type, price, beds, baths, description) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (user["id"], title, location, ltype, price, beds, baths, description or None),
        )
        listing_id = cursor.lastrowid
        for order, (token, data, mime) in enumerate(photos):
            cursor.execute(
                "INSERT INTO listing_images (listing_id, token, data, mime, sort_order) VALUES (%s, %s, %s, %s, %s)",
                (listing_id, token, data, mime, order),
            )
        conn.commit()  # listing and photos are saved together or not at all
        listing = fetch_listings(cursor, "WHERE l.id = %s", (listing_id,))[0]
        return jsonify({"message": "Your property listing has been created successfully.", "listing": listing}), 201
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while creating a listing")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.put("/api/listings/<int:listing_id>")
def update_listing(listing_id):
    """Update a landlord's listing. multipart/form-data: same fields as create, with
    optional new photos replacing the current set when provided."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] != "landlord":
        return jsonify({"error": "Only landlords can update listings."}), 403

    form = request.form
    title = (form.get("title") or "").strip()
    location = (form.get("location") or "").strip()
    ltype = (form.get("type") or "").strip()
    description = (form.get("description") or "").strip()
    try:
        price = round(float(form.get("price", "")), 2)
    except ValueError:
        price = 0
    beds = int_in_range(form.get("beds", 0), 0, 50)
    baths = int_in_range(form.get("baths", 1), 1, 50)

    if not title or len(title) > 120:
        return jsonify({"error": "Add a title (up to 120 characters)."}), 400
    if not location or len(location) > 160:
        return jsonify({"error": "Add a location (up to 160 characters)."}), 400
    if ltype not in LISTING_TYPES:
        return jsonify({"error": "Choose a valid property type."}), 400
    if not (0 < price <= 99999999):
        return jsonify({"error": "Enter a monthly price above 0."}), 400
    if beds is None or baths is None:
        return jsonify({"error": "Beds must be 0 or more and baths at least 1."}), 400
    if len(description) > 5000:
        return jsonify({"error": "The description is too long (5000 characters max)."}), 400

    uploads = [f for f in request.files.getlist("photo") + request.files.getlist("photos") if f and f.filename]
    if len(uploads) > MAX_LISTING_PHOTOS:
        return jsonify({"error": f"You can upload up to {MAX_LISTING_PHOTOS} photos."}), 400

    photos = []
    for upload in uploads:
        data = upload.read(MAX_AVATAR_BYTES + 1)
        if len(data) > MAX_AVATAR_BYTES:
            return jsonify({"error": "A photo is too big. Please choose ones under 2 MB."}), 413
        ext = detect_image_ext(data)
        if not ext:
            return jsonify({"error": "Please upload JPG, PNG or WEBP images."}), 400
        photos.append((secrets.token_hex(16), data, MIME_BY_EXT[ext]))

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM listings WHERE id = %s AND landlord_id = %s",
            (listing_id, user["id"]),
        )
        if cursor.fetchone() is None:
            return jsonify({"error": "Listing not found."}), 404

        cursor.execute(
            "UPDATE listings SET title = %s, location = %s, type = %s, price = %s, beds = %s, baths = %s, description = %s WHERE id = %s AND landlord_id = %s",
            (title, location, ltype, price, beds, baths, description or None, listing_id, user["id"]),
        )
        if uploads:
            cursor.execute("DELETE FROM listing_images WHERE listing_id = %s", (listing_id,))
            for order, (token, data, mime) in enumerate(photos):
                cursor.execute(
                    "INSERT INTO listing_images (listing_id, token, data, mime, sort_order) VALUES (%s, %s, %s, %s, %s)",
                    (listing_id, token, data, mime, order),
                )
        conn.commit()
        listing = fetch_listings(cursor, "WHERE l.id = %s", (listing_id,))[0]
        return jsonify({"message": "Listing updated.", "listing": listing}), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while updating a listing")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.delete("/api/listings/<int:listing_id>")
def delete_listing(listing_id):
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] != "landlord":
        return jsonify({"error": "Only landlords can delete listings."}), 403
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        # Only the owner's own listing matches. Photos and reviews are removed by ON DELETE CASCADE.
        cursor.execute("DELETE FROM listings WHERE id = %s AND landlord_id = %s", (listing_id, user["id"]))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Listing not found."}), 404
        return jsonify({"message": "Listing deleted."}), 200
    except Error as exc:
        app.logger.exception("Database error while deleting a listing")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/listing-image/<token>")
def listing_image(token):
    """Serve a listing photo from the database. Tokens are random and change per upload."""
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT data, mime FROM listing_images WHERE token = %s", (token,))
        row = cursor.fetchone()
    except Error:
        app.logger.exception("Database error while loading a listing photo")
        return jsonify({"error": "Could not load the photo."}), 500
    finally:
        close_db(conn, cursor)
    if not row or not row[0]:
        return jsonify({"error": "Not found"}), 404
    resp = Response(bytes(row[0]), mimetype=row[1] or "application/octet-stream")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp

@app.get("/api/listings/<int:listing_id>/reviews")
def get_reviews(listing_id):
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT 1 FROM listings WHERE id = %s", (listing_id,))
        if cursor.fetchone() is None:
            return jsonify({"error": "Listing not found."}), 404
        cursor.execute(
            "SELECT r.id, r.rating, r.comment, r.created_at, u.full_name AS reviewer "
            "FROM reviews r JOIN users u ON u.id = r.tenant_id "
            "WHERE r.listing_id = %s ORDER BY r.created_at DESC, r.id DESC",
            (listing_id,),
        )
        reviews = [
            {"id": r["id"], "rating": r["rating"], "comment": r["comment"],
             "reviewer": r["reviewer"], "created_at": iso(r["created_at"])}
            for r in cursor.fetchall()
        ]
        count = len(reviews)
        average = round(sum(r["rating"] for r in reviews) / count, 2) if count else None
        return jsonify({"reviews": reviews, "count": count, "average": average}), 200
    except Error as exc:
        app.logger.exception("Database error while loading reviews")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/listings/<int:listing_id>/reviews")
def add_review(listing_id):
    """Logged-in tenants only, one review per tenant per listing.
    NOTE: rentals are not stored in the database yet, so a completed-rental check can't be enforced."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in to write a review."}), 401
    if user["role"] != "tenant":
        return jsonify({"error": "Only tenants can write reviews."}), 403

    body = request.get_json(silent=True) or {}
    rating = body.get("rating")
    if isinstance(rating, str) and rating.strip().isdigit():
        rating = int(rating.strip())
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return jsonify({"error": "Choose a star rating from 1 to 5."}), 400
    comment = str(body.get("comment") or "").strip()
    if len(comment) < 5:
        return jsonify({"error": "Write at least a short review (5 characters)."}), 400
    if len(comment) > 1000:
        return jsonify({"error": "Your review is too long (1000 characters max)."}), 400

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT landlord_id FROM listings WHERE id = %s", (listing_id,))
        listing = cursor.fetchone()
        if not listing:
            return jsonify({"error": "Listing not found."}), 404
        if listing["landlord_id"] == user["id"]:
            return jsonify({"error": "You can't review your own listing."}), 403
        cursor.execute(
            "INSERT INTO reviews (listing_id, tenant_id, rating, comment) VALUES (%s, %s, %s, %s)",
            (listing_id, user["id"], rating, comment),
        )
        conn.commit()
        return jsonify({"message": "Thanks! Your review has been posted."}), 201
    except Error as exc:
        if conn:
            conn.rollback()
        if getattr(exc, "errno", None) == 1062:  # UNIQUE (listing_id, tenant_id)
            return jsonify({"error": "You already reviewed this home."}), 409
        app.logger.exception("Database error while saving a review")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

# ---------------------------------------------------------------------------
# Tenants, monthly bills and payment verification (landlord + tenant dashboards)
# ---------------------------------------------------------------------------
MONTH_RE = _re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def role_required(role):
    """Return (user, None) when logged in with the right role, else (None, error response)."""
    user = current_user()
    if not user:
        return None, (jsonify({"error": "Please log in first."}), 401)
    if user["role"] != role:
        return None, (jsonify({"error": f"Only {role}s can do this."}), 403)
    return user, None

def parse_date(raw):
    try:
        return datetime.strptime(str(raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None

def money(raw):
    """A non-negative amount with at most 2 decimals, or None when it is not a valid number."""
    try:
        value = round(float(str(raw).strip() or 0), 2)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 99999999 else None

def rental_request_json(row):
    return {
        "id": row["id"],
        "listing_id": row["listing_id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row["tenant_name"],
        "tenant_email": row["tenant_email"],
        "title": row["title"],
        "location": row["location"],
        "move_in": row["move_in"].isoformat(),
        "months": row["months"],
        "monthly_price": whole_or_float(row["monthly_price"]),
        "total": whole_or_float(row["monthly_price"] * row["months"]),
        "status": row["status"],
        "payment_method": row["payment_method"],
        "payment_reference": row["payment_reference"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "paid_at": iso(row["paid_at"]),
    }

RENTAL_REQUEST_SELECT = (
    "SELECT rr.id, rr.listing_id, rr.tenant_id, rr.move_in, rr.months, rr.monthly_price, "
    "rr.status, rr.payment_method, rr.payment_reference, rr.created_at, rr.updated_at, rr.paid_at, "
    "l.title, l.location, u.full_name AS tenant_name, u.email AS tenant_email "
    "FROM rental_requests rr JOIN listings l ON l.id = rr.listing_id "
    "JOIN users u ON u.id = rr.tenant_id "
)

@app.get("/api/rental-requests")
def list_rental_requests():
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] == "landlord":
        where, params = "WHERE l.landlord_id = %s ", (user["id"],)
    else:
        where, params = "WHERE rr.tenant_id = %s ", (user["id"],)
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(RENTAL_REQUEST_SELECT + where + "ORDER BY rr.created_at DESC, rr.id DESC", params)
        requests = [rental_request_json(row) for row in cursor.fetchall()]
        return jsonify({"requests": requests}), 200
    except Error as exc:
        app.logger.exception("Database error while loading rental requests")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/rental-requests")
def create_rental_request():
    user, err = role_required("tenant")
    if err:
        return err
    body = request.get_json(silent=True) or {}
    listing_id = int_in_range(body.get("listing_id"), 1, 2**63 - 1)
    move_in = parse_date(body.get("move_in"))
    months = int_in_range(body.get("months"), 1, 12)
    if listing_id is None:
        return jsonify({"error": "Choose a valid listing."}), 400
    if move_in is None or move_in < datetime.utcnow().date():
        return jsonify({"error": "Choose a move-in date from today onward."}), 400
    if months is None:
        return jsonify({"error": "Choose a stay between 1 and 12 months."}), 400

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, landlord_id, status, price FROM listings WHERE id = %s",
            (listing_id,),
        )
        listing = cursor.fetchone()
        if not listing or listing["status"] != "available":
            return jsonify({"error": "That home is no longer available."}), 404
        if listing["landlord_id"] == user["id"]:
            return jsonify({"error": "You can't request your own listing."}), 403
        cursor.execute(
            "SELECT id FROM rental_requests WHERE listing_id = %s AND status IN ('approved', 'paid') LIMIT 1",
            (listing_id,),
        )
        if cursor.fetchone():
            return jsonify({"error": "Another tenant has already been approved for this home."}), 409
        cursor.execute(
            "SELECT id FROM rental_requests WHERE listing_id = %s AND tenant_id = %s "
            "AND status IN ('pending', 'approved') LIMIT 1",
            (listing_id, user["id"]),
        )
        if cursor.fetchone():
            return jsonify({"error": "You already have an active request for this home."}), 409
        cursor.execute(
            "INSERT INTO rental_requests (listing_id, tenant_id, move_in, months, monthly_price) "
            "VALUES (%s, %s, %s, %s, %s)",
            (listing_id, user["id"], move_in, months, listing["price"]),
        )
        request_id = cursor.lastrowid
        conn.commit()
        cursor.execute(RENTAL_REQUEST_SELECT + "WHERE rr.id = %s", (request_id,))
        return jsonify({
            "message": "Your rental request was sent to the landlord.",
            "request": rental_request_json(cursor.fetchone()),
        }), 201
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while creating a rental request")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/rental-requests/<int:request_id>/decision")
def decide_rental_request(request_id):
    user, err = role_required("landlord")
    if err:
        return err
    action = str((request.get_json(silent=True) or {}).get("action", "")).strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "Choose approve or reject."}), 400

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT rr.id, rr.listing_id, rr.status FROM rental_requests rr "
            "JOIN listings l ON l.id = rr.listing_id "
            "WHERE rr.id = %s AND l.landlord_id = %s FOR UPDATE",
            (request_id, user["id"]),
        )
        rental_request = cursor.fetchone()
        if not rental_request:
            return jsonify({"error": "Rental request not found."}), 404
        if rental_request["status"] != "pending":
            return jsonify({"error": "This request has already been handled."}), 409

        new_status = "approved" if action == "approve" else "rejected"
        if action == "approve":
            cursor.execute(
                "SELECT status FROM listings WHERE id = %s FOR UPDATE",
                (rental_request["listing_id"],),
            )
            listing = cursor.fetchone()
            if not listing or listing["status"] != "available":
                return jsonify({"error": "This home is no longer available."}), 409
            cursor.execute(
                "SELECT id FROM rental_requests WHERE listing_id = %s AND id <> %s "
                "AND status IN ('approved', 'paid') LIMIT 1",
                (rental_request["listing_id"], request_id),
            )
            if cursor.fetchone():
                return jsonify({"error": "Another tenant has already been approved for this home."}), 409
        cursor.execute(
            "UPDATE rental_requests SET status = %s WHERE id = %s",
            (new_status, request_id),
        )
        conn.commit()
        return jsonify({
            "message": "Rental request approved. The tenant can now continue to payment." if action == "approve"
                else "Rental request rejected.",
            "status": new_status,
        }), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while deciding a rental request")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/rental-requests/<int:request_id>/pay")
def pay_rental_request(request_id):
    user, err = role_required("tenant")
    if err:
        return err
    body = request.get_json(silent=True) or {}
    method = str(body.get("method") or "").strip()
    reference = str(body.get("reference") or "").strip()
    allowed_methods = {
        "GCash", "Maya", "Credit / debit card",
        "BDO bank transfer", "BPI bank transfer", "UnionBank transfer",
    }
    if method not in allowed_methods:
        return jsonify({"error": "Choose a payment method."}), 400
    if not reference or len(reference) > 100:
        return jsonify({"error": "A valid payment reference is required."}), 400

    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT rr.id, rr.listing_id, rr.status, rr.months, rr.monthly_price, "
            "l.status AS listing_status, l.landlord_id, l.title AS listing_title "
            "FROM rental_requests rr JOIN listings l ON l.id = rr.listing_id "
            "WHERE rr.id = %s AND rr.tenant_id = %s FOR UPDATE",
            (request_id, user["id"]),
        )
        rental_request = cursor.fetchone()
        if not rental_request:
            return jsonify({"error": "Rental request not found."}), 404
        if rental_request["status"] != "approved":
            return jsonify({"error": "This rental request is not approved for payment."}), 409
        if rental_request["listing_status"] != "available":
            return jsonify({"error": "This home is no longer available."}), 409
        cursor.execute(
            "UPDATE rental_requests SET status = 'paid', payment_method = %s, "
            "payment_reference = %s, paid_at = NOW() WHERE id = %s AND status = 'approved'",
            (method, reference, request_id),
        )
        cursor.execute(
            "UPDATE listings SET status = 'rented' WHERE id = %s AND status = 'available'",
            (rental_request["listing_id"],),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"error": "This home is no longer available."}), 409
        cursor.execute(
            "UPDATE rental_requests SET status = 'rejected' "
            "WHERE listing_id = %s AND id <> %s AND status = 'pending'",
            (rental_request["listing_id"], request_id),
        )
        cursor.execute(
            "SELECT id FROM tenants WHERE landlord_id = %s "
            "AND (listing_id = %s OR listing_id IS NULL) AND user_email = %s "
            "ORDER BY listing_id IS NULL LIMIT 1 FOR UPDATE",
            (rental_request["landlord_id"], rental_request["listing_id"], user["email"].strip().lower()),
        )
        tenant = cursor.fetchone()
        if tenant:
            cursor.execute(
                "UPDATE tenants SET listing_id = %s, name = %s, unit = %s, rent = %s, status = 'Active' "
                "WHERE id = %s AND landlord_id = %s",
                (rental_request["listing_id"], user["name"], rental_request["listing_title"], rental_request["monthly_price"],
                 tenant["id"], rental_request["landlord_id"]),
            )
        else:
            cursor.execute(
                "INSERT INTO tenants (landlord_id, listing_id, user_email, name, unit, rent, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'Active')",
                (rental_request["landlord_id"], rental_request["listing_id"],
                 user["email"].strip().lower(), user["name"], rental_request["listing_title"],
                 rental_request["monthly_price"]),
            )
        conn.commit()
        return jsonify({"message": "Demo payment recorded.", "reference": reference}), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while recording rental payment")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

BILL_SELECT = (
    "SELECT b.id, b.tenant_id, b.month, b.rent AS bill_rent, b.extra, b.total, b.due_date, b.status, b.reference, b.paid_on, "
    "t.name AS tenant_name, t.unit, t.listing_id, l.title AS listing_title, "
    "(b.status = 'Unpaid' AND b.due_date < CURDATE()) AS is_overdue "
    "FROM bills b JOIN tenants t ON t.id = b.tenant_id "
    "LEFT JOIN listings l ON l.id = t.listing_id "
)

def bill_json(r):
    status = "Overdue" if r["is_overdue"] else r["status"]
    return {
        "id": r["id"], "tenant_id": r["tenant_id"], "tenant_name": r["tenant_name"], "unit": r["unit"],
        "listing_id": r["listing_id"], "listing_title": r["listing_title"],
        "rent": whole_or_float(r["bill_rent"]), "extra": whole_or_float(r["extra"]),
        "month": r["month"], "total": whole_or_float(r["total"]),
        "due_date": r["due_date"].isoformat() if r["due_date"] else None,
        "paid_on": r["paid_on"].isoformat() if r["paid_on"] else None,
        "reference": r["reference"], "status": status,
    }

@app.get("/api/tenants")
def list_tenants():
    user, err = role_required("landlord")
    if err:
        return err
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT t.id, t.name, t.unit, t.rent, t.status, t.user_email, t.listing_id, "
            "l.title AS listing_title FROM tenants t LEFT JOIN listings l ON l.id = t.listing_id "
            "WHERE t.landlord_id = %s "
            "ORDER BY t.created_at DESC, t.id DESC", (user["id"],))
        tenants = [
            {"id": r["id"], "name": r["name"], "unit": r["unit"], "rent": whole_or_float(r["rent"]),
             "status": r["status"], "email": r["user_email"], "listing_id": r["listing_id"],
             "listing_title": r["listing_title"]}
            for r in cursor.fetchall()
        ]
        return jsonify({"tenants": tenants}), 200
    except Error as exc:
        app.logger.exception("Database error while listing tenants")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/tenants")
def create_tenant():
    user, err = role_required("landlord")
    if err:
        return err
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    unit = str(body.get("unit") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    raw_listing_id = body.get("listing_id")
    listing_id = int_in_range(raw_listing_id, 1, 2**63 - 1) if raw_listing_id not in (None, "") else None
    rent = money(body.get("rent"))
    if not name or len(name) > 100:
        return jsonify({"error": "Enter the tenant's full name (up to 100 characters)."}), 400
    if not unit or len(unit) > 160:
        return jsonify({"error": "Enter the unit (up to 160 characters)."}), 400
    if not rent:
        return jsonify({"error": "Enter a monthly rent above 0."}), 400
    if email and (len(email) > 255 or not EMAIL_RE.match(email)):
        return jsonify({"error": "That email address doesn't look right."}), 400
    if raw_listing_id not in (None, "") and listing_id is None:
        return jsonify({"error": "Choose a valid listing."}), 400
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        if listing_id is not None:
            cursor.execute("SELECT id FROM listings WHERE id = %s AND landlord_id = %s", (listing_id, user["id"]))
            if not cursor.fetchone():
                return jsonify({"error": "Choose one of your own listings."}), 400
        cursor.execute(
            "INSERT INTO tenants (landlord_id, listing_id, user_email, name, unit, rent) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user["id"], listing_id, email or None, name, unit, rent))
        conn.commit()
        return jsonify({"message": "Tenant added.", "id": cursor.lastrowid}), 201
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while adding a tenant")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/tenants/<int:tenant_id>/listing")
def assign_tenant_listing(tenant_id):
    user, err = role_required("landlord")
    if err:
        return err
    listing_id = int_in_range((request.get_json(silent=True) or {}).get("listing_id"), 1, 2**63 - 1)
    if listing_id is None:
        return jsonify({"error": "Choose a valid listing."}), 400
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tenants WHERE id = %s AND landlord_id = %s", (tenant_id, user["id"]))
        if cursor.fetchone() is None:
            return jsonify({"error": "Tenant not found."}), 404
        cursor.execute("SELECT id FROM listings WHERE id = %s AND landlord_id = %s", (listing_id, user["id"]))
        if cursor.fetchone() is None:
            return jsonify({"error": "Choose one of your own listings."}), 400
        cursor.execute(
            "UPDATE tenants SET listing_id = %s WHERE id = %s AND landlord_id = %s",
            (listing_id, tenant_id, user["id"]),
        )
        conn.commit()
        return jsonify({"message": "Tenant and their bills are now linked to this listing."}), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while linking a tenant to a listing")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/bills")
def list_bills():
    """Landlords see the bills of their tenants. Tenants see only bills made out to their own email."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    if user["role"] == "landlord":
        where, params = "WHERE b.landlord_id = %s ", (user["id"],)
    else:
        where, params = "WHERE t.user_email = %s ", (user["email"].strip().lower(),)
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(BILL_SELECT + where + "ORDER BY b.due_date DESC, b.id DESC", params)
        return jsonify({"bills": [bill_json(r) for r in cursor.fetchall()]}), 200
    except Error as exc:
        app.logger.exception("Database error while listing bills")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/bills")
def create_bill():
    user, err = role_required("landlord")
    if err:
        return err
    body = request.get_json(silent=True) or {}
    month = str(body.get("month") or "").strip()
    due = parse_date(body.get("due_date"))
    extra = money(body.get("extra"))
    tenant_id = int_in_range(body.get("tenant_id"), 1, 2**63 - 1)
    if tenant_id is None:
        return jsonify({"error": "Choose a tenant."}), 400
    if not MONTH_RE.match(month):
        return jsonify({"error": "Choose the billing month."}), 400
    if due is None:
        return jsonify({"error": "Choose a due date."}), 400
    if extra is None:
        return jsonify({"error": "Extra charges must be 0 or more."}), 400
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        # The tenant must belong to THIS landlord and still be active.
        cursor.execute("SELECT rent FROM tenants WHERE id = %s AND landlord_id = %s AND status = 'Active'",
                       (tenant_id, user["id"]))
        tenant = cursor.fetchone()
        if not tenant:
            return jsonify({"error": "Tenant not found."}), 404
        rent = float(tenant["rent"])
        cursor.execute(
            "INSERT INTO bills (landlord_id, tenant_id, month, rent, extra, total, due_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user["id"], tenant_id, month, rent, extra, round(rent + extra, 2), due))
        conn.commit()
        return jsonify({"message": "Bill added.", "id": cursor.lastrowid}), 201
    except Error as exc:
        if conn:
            conn.rollback()
        if getattr(exc, "errno", None) == 1062:  # UNIQUE (tenant_id, month)
            return jsonify({"error": "That tenant already has a bill for this month."}), 409
        app.logger.exception("Database error while adding a bill")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/bills/<int:bill_id>/submit-payment")
def submit_payment(bill_id):
    """Tenant says 'I paid' with a reference number. The bill waits for the landlord to verify it."""
    user, err = role_required("tenant")
    if err:
        return err
    body = request.get_json(silent=True) or {}
    reference = str(body.get("reference") or "").strip()
    paid_on = parse_date(body.get("paid_on")) or datetime.utcnow().date()
    if not reference or len(reference) > 100:
        return jsonify({"error": "Enter a reference number (up to 100 characters)."}), 400
    if paid_on > datetime.utcnow().date() + timedelta(days=1):
        return jsonify({"error": "The payment date can't be in the future."}), 400
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE bills b JOIN tenants t ON t.id = b.tenant_id "
            "SET b.status = 'Pending', b.reference = %s, b.paid_on = %s "
            "WHERE b.id = %s AND b.status = 'Unpaid' AND t.user_email = %s",
            (reference, paid_on, bill_id, user["email"].strip().lower()))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "This bill can't be paid right now."}), 404
        return jsonify({"message": "Payment submitted. Awaiting verification."}), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while submitting a payment")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.post("/api/bills/<int:bill_id>/verify")
def verify_payment(bill_id):
    """Landlord approves (-> Paid) or rejects (-> Unpaid again) a payment the tenant submitted."""
    user, err = role_required("landlord")
    if err:
        return err
    action = str((request.get_json(silent=True) or {}).get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "Choose approve or reject."}), 400
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor()
        if action == "approve":
            cursor.execute("UPDATE bills SET status = 'Paid' WHERE id = %s AND landlord_id = %s AND status = 'Pending'",
                           (bill_id, user["id"]))
        else:
            cursor.execute("UPDATE bills SET status = 'Unpaid', reference = NULL, paid_on = NULL "
                           "WHERE id = %s AND landlord_id = %s AND status = 'Pending'", (bill_id, user["id"]))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "No pending payment found for this bill."}), 404
        return jsonify({"message": "Payment approved." if action == "approve" else "Payment rejected."}), 200
    except Error as exc:
        if conn:
            conn.rollback()
        app.logger.exception("Database error while verifying a payment")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/landlord/stats")
def landlord_stats():
    user, err = role_required("landlord")
    if err:
        return err
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS n FROM tenants WHERE landlord_id = %s AND status = 'Active'", (user["id"],))
        tenants = cursor.fetchone()["n"]
        cursor.execute(
            "SELECT COUNT(*) AS n FROM listings WHERE landlord_id = %s AND status = 'available'",
            (user["id"],),
        )
        active_listings = cursor.fetchone()["n"]
        cursor.execute(
            "SELECT COALESCE(SUM(CASE WHEN status = 'Paid' "
            "AND YEAR(paid_on) = YEAR(CURDATE()) AND MONTH(paid_on) = MONTH(CURDATE()) "
            "THEN total END), 0) AS collected, "
            "COALESCE(SUM(status = 'Pending'), 0) AS pending, "
            "COALESCE(SUM(status = 'Unpaid' AND due_date < CURDATE()), 0) AS overdue "
            "FROM bills WHERE landlord_id = %s", (user["id"],))
        row = cursor.fetchone()
        cursor.execute(
            "SELECT COALESCE(SUM(rr.monthly_price * rr.months), 0) AS collected "
            "FROM rental_requests rr JOIN listings l ON l.id = rr.listing_id "
            "WHERE l.landlord_id = %s AND rr.status = 'paid' "
            "AND YEAR(rr.paid_at) = YEAR(CURDATE()) AND MONTH(rr.paid_at) = MONTH(CURDATE())",
            (user["id"],),
        )
        listing_payments = cursor.fetchone()["collected"]
        return jsonify({"tenants": tenants, "active_listings": active_listings,
                        "collected": whole_or_float(row["collected"] + listing_payments),
                        "pending": int(row["pending"]), "overdue": int(row["overdue"])}), 200
    except Error as exc:
        app.logger.exception("Database error while loading landlord stats")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

@app.get("/api/tenant/stats")
def tenant_stats():
    user, err = role_required("tenant")
    if err:
        return err
    email = user["email"].strip().lower()
    conn = cursor = None
    try:
        conn = db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS n, COALESCE(SUM(rent), 0) AS monthly "
                       "FROM tenants WHERE user_email = %s AND status = 'Active'", (email,))
        rentals = cursor.fetchone()
        cursor.execute(
            "SELECT COALESCE(SUM(b.total), 0) AS balance, MIN(b.due_date) AS next_due "
            "FROM bills b JOIN tenants t ON t.id = b.tenant_id "
            "WHERE t.user_email = %s AND b.status = 'Unpaid'", (email,))
        bills = cursor.fetchone()
        return jsonify({
            "active": rentals["n"], "monthly": whole_or_float(rentals["monthly"]),
            "balance": whole_or_float(bills["balance"]),
            "next_due": bills["next_due"].isoformat() if bills["next_due"] else None,
        }), 200
    except Error as exc:
        app.logger.exception("Database error while loading tenant stats")
        return db_error_response(exc)
    finally:
        close_db(conn, cursor)

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
            # Older databases were created before the profile page existed: add the new columns.
            for column, ddl in (
                ("phone", "VARCHAR(20) NULL"),
                ("avatar", "VARCHAR(255) NULL"),
                ("avatar_data", "MEDIUMBLOB NULL"),
                ("avatar_mime", "VARCHAR(30) NULL"),
            ):
                cursor.execute(
                    "SELECT 1 FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = %s",
                    (column,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
            cursor.execute(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tenants' AND COLUMN_NAME = 'listing_id'"
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "ALTER TABLE tenants ADD COLUMN listing_id BIGINT UNSIGNED NULL, "
                    "ADD KEY idx_tenants_listing (listing_id), "
                    "ADD CONSTRAINT fk_tenants_listing FOREIGN KEY (listing_id) "
                    "REFERENCES listings(id) ON DELETE SET NULL"
                )
            cursor.execute(
                "UPDATE tenants t JOIN ("
                "SELECT landlord_id, LOWER(TRIM(title)) AS title_key, MIN(id) AS listing_id "
                "FROM listings GROUP BY landlord_id, LOWER(TRIM(title)) HAVING COUNT(*) = 1"
                ") l ON l.landlord_id = t.landlord_id "
                "AND l.title_key = LOWER(TRIM(t.unit)) "
                "SET t.listing_id = l.listing_id WHERE t.listing_id IS NULL"
            )
            cursor.execute(
                "INSERT INTO tenants (landlord_id, listing_id, user_email, name, unit, rent, status) "
                "SELECT l.landlord_id, l.id, LOWER(TRIM(u.email)), u.full_name, l.title, "
                "rr.monthly_price, 'Active' "
                "FROM rental_requests rr "
                "JOIN listings l ON l.id = rr.listing_id "
                "JOIN users u ON u.id = rr.tenant_id "
                "WHERE rr.status = 'paid' AND NOT EXISTS ("
                "SELECT 1 FROM tenants t WHERE t.landlord_id = l.landlord_id "
                "AND t.listing_id = l.id AND LOWER(TRIM(t.user_email)) = LOWER(TRIM(u.email))"
                ")"
            )
            conn.commit()

            # One-time move: photos saved as files by older versions go into the database.
            cursor.execute("SELECT id, avatar FROM users WHERE avatar IS NOT NULL AND avatar_data IS NULL")
            for user_id, filename in cursor.fetchall():
                path = LEGACY_AVATAR_DIR / Path(filename).name
                ext = path.suffix.lstrip(".").lower()
                if path.is_file() and ext in MIME_BY_EXT:
                    cursor.execute(
                        "UPDATE users SET avatar_data = %s, avatar_mime = %s WHERE id = %s",
                        (path.read_bytes(), MIME_BY_EXT[ext], user_id),
                    )
                else:
                    cursor.execute("UPDATE users SET avatar = NULL WHERE id = %s", (user_id,))
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