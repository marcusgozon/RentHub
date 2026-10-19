# RentHub

A rental-listing website with a **Flask** (Python) backend and a **MySQL** database. The frontend is plain HTML, CSS and JavaScript that Flask serves from the `frontend/` folder.

Current features: sign-up and login with emailed 6-digit verification codes (2FA), duplicate-email protection, tenant/landlord roles, and a profile page with avatar upload.

---

## Contents

1. [What you need first](#1-what-you-need-first)
2. [Clone the project](#2-clone-the-project)
3. [Create a virtual environment](#3-create-a-virtual-environment)
4. [Install Flask and the other packages](#4-install-flask-and-the-other-packages)
5. [Set up MySQL](#5-set-up-mysql)
6. [Optional: use a `.env` file](#6-optional-use-a-env-file)
7. [Run the app](#7-run-the-app)
8. [Test that everything works](#8-test-that-everything-works)
9. [Troubleshooting](#9-troubleshooting)
10. [Moving existing data to another device](#10-moving-existing-data-to-another-device)
11. [Project structure](#project-structure)
12. [Notes and limitations](#notes-and-limitations)

---

## 1. What you need first

| Tool | Notes |
| --- | --- |
| **Git** | To clone the repository. |
| **Python 3.10 or newer** | The project was built on Python 3.14. On Windows, tick **Add python.exe to PATH** in the installer. |
| **MySQL Server 8.x** | Remember the `root` password you set during installation. |
| **MySQL Workbench** (optional) | A GUI for running SQL. The command line works too. |
| **Internet access** | Needed to install packages and to send verification emails through Gmail. |

Check the installs:

```powershell
git --version
py --version        # Windows. On macOS/Linux use: python3 --version
mysql --version
```

> If `mysql` is not recognised on Windows, add MySQL's `bin` folder to your PATH. It is usually
> `C:\Program Files\MySQL\MySQL Server 8.0\bin` (the version number in the folder name may differ).

---

## 2. Clone the project

```bash
git clone https://github.com/marcusgozon/RentHub.git
cd RentHub
```

All commands below are run from this project root folder.

---

## 3. Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of your computer. The `.venv/` folder is **not** stored in Git, so every device must create its own. Never copy a `.venv` folder from another computer.

**Windows (PowerShell, e.g. the VS Code terminal)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says *running scripts is disabled on this system*, run this once and activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Windows (Command Prompt)**

```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it is active, your prompt starts with `(.venv)`. Run the activate command again every time you open a new terminal.

---

## 4. Install Flask and the other packages

With the environment active:

```bash
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

This installs everything the backend needs:

| Package | Used for |
| --- | --- |
| `Flask` | The web server and API |
| `mysql-connector-python` | Connecting to MySQL |
| `python-dotenv` | Reading the optional `.env` file |

If you prefer to install them by hand, this does the same thing:

```bash
pip install Flask mysql-connector-python python-dotenv
```

Confirm the install:

```bash
pip list
```

You should see Flask, mysql-connector-python and python-dotenv in the list.

---

## 5. Set up MySQL

### 5.1 Make sure MySQL is running

**Windows:** open *Services* (`Win + R`, type `services.msc`) and check that a service named like `MySQL80` is **Running**. Or from an administrator PowerShell:

```powershell
Get-Service *mysql*
net start MySQL80
```

**macOS (Homebrew):** `brew services start mysql`
**Linux:** `sudo systemctl start mysql`

### 5.2 The connection settings the app uses

The backend reads its database settings from the `HARDCODED` block near the top of `backend/app.py`. The values are:

| Setting | Value | Meaning |
| --- | --- | --- |
| `DB_HOST` | `localhost` | MySQL is on this same computer |
| `DB_PORT` | `3306` | MySQL's default port |
| `DB_USER` | `root` | The MySQL user the app logs in as |
| `DB_PASSWORD` | *the value on the `DB_PASSWORD` line in `backend/app.py`* | Must match your MySQL `root` password |
| `DB_NAME` | `renthub_db` | The database the app uses |

**Your MySQL server has to match these.** There are three ways to make it work:

1. **Match the app (simplest):** set your MySQL `root` password to the same value as `DB_PASSWORD` in `app.py`. On an existing server you can change it with:
   ```sql
   ALTER USER 'root'@'localhost' IDENTIFIED BY 'the-password-from-app.py';
   ```
2. **Edit `HARDCODED` in `app.py`** so `DB_PASSWORD` (and anything else) matches your server.
3. **Use a `.env` file** to override the values without touching `app.py`. See [section 6](#6-optional-use-a-env-file).

A real environment variable or a `.env` value always wins over the `HARDCODED` block.

### 5.3 Test the connection

```bash
mysql -u root -p
```

Enter the password. If you reach the `mysql>` prompt, the credentials work. If you see `ERROR 1045 (28000): Access denied`, the password is wrong; see [Troubleshooting](#9-troubleshooting).

### 5.4 Create the database

The app connects straight to `renthub_db`, so **the database must exist before you start the server**. At the `mysql>` prompt:

```sql
CREATE DATABASE IF NOT EXISTS renthub_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 5.5 Create the tables

The app needs three tables: `users`, `login_codes` and `pending_signups`. This is the full SQL; it is identical to `database/schema.sql` and is safe to run more than once (`IF NOT EXISTS`).

```sql
CREATE DATABASE IF NOT EXISTS renthub_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE renthub_db;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('tenant', 'landlord') NOT NULL DEFAULT 'tenant',
    phone VARCHAR(20) NULL,
    avatar VARCHAR(255) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Two-factor login codes: one active code per user, stored as a hash (never the code itself).
CREATE TABLE IF NOT EXISTS login_codes (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    code_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_login_codes_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Signups waiting for their emailed code. The real account is only created in `users`
-- after the code is verified. Passwords are stored as a hash; the code is stored hashed too.
CREATE TABLE IF NOT EXISTS pending_signups (
    email VARCHAR(255) NOT NULL PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('tenant', 'landlord') NOT NULL DEFAULT 'tenant',
    code_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
);
```

Pick whichever way you like to run it:

**A. In the `mysql>` shell.** Start `mysql` from the project root, then:

```sql
SOURCE database/schema.sql;
```

(If you started it somewhere else, give the full path with forward slashes, e.g. `SOURCE C:/Users/you/RentHub/database/schema.sql;`.)

**B. In MySQL Workbench.** Connect to your local server, use *File > Open SQL Script* to open `database/schema.sql`, then click the lightning bolt (Execute).

**C. Let the app do it.** When the backend starts, `ensure_schema()` in `app.py` runs `schema.sql` and creates any missing tables, as long as the `renthub_db` database from step 5.4 already exists. Even so, running the SQL yourself once is a good way to confirm everything is fine.

> **PowerShell note:** do not use `mysql -u root -p < database/schema.sql` in PowerShell. The `<` operator is not supported there. Use method A or B, or run it through Command Prompt: `cmd /c "mysql -u root -p < database\schema.sql"`.

### 5.6 Verify the tables

```sql
USE renthub_db;
SHOW TABLES;
DESCRIBE users;
```

`SHOW TABLES;` should list `login_codes`, `pending_signups` and `users`.

### 5.7 Optional: a dedicated MySQL user instead of `root`

Safer than using `root`, especially before any deployment:

```sql
CREATE USER 'renthub'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON renthub_db.* TO 'renthub'@'localhost';
FLUSH PRIVILEGES;
```

Then set `DB_USER` and `DB_PASSWORD` to match, in a `.env` file or in `app.py`.

---

## 6. Optional: use a `.env` file

A `.env` file in the project root overrides the `HARDCODED` values in `app.py`. It is listed in `.gitignore`, so it is never pushed to GitHub, which makes it the right place for passwords.

```bash
# Windows PowerShell
Copy-Item .env.example .env
# macOS / Linux
cp .env.example .env
```

Open `.env` and fill in your own values:

```ini
DB_PASSWORD=your-mysql-password
# DB_HOST=localhost
# DB_PORT=3306
# DB_USER=root
# DB_NAME=renthub_db

RENTHUB_SECRET_KEY=any-long-random-text

GMAIL_USER=the-gmail-address-that-sends-codes@gmail.com
GMAIL_APP_PASSWORD=your-16-character-google-app-password
```

- `RENTHUB_SECRET_KEY` signs login sessions and hashes the emailed codes. Keep it fixed so sessions survive restarts. To generate one: `python -c "import secrets; print(secrets.token_hex(32))"`
- Gmail **App Password**: in the Google account that will send the emails, turn on 2-Step Verification, then go to *Google Account > Security > App passwords* and create one. A normal Gmail password will not work.
- The `.env` file stays on your computer. On every new device you must create it again or copy it over yourself.

---

## 7. Run the app

With the virtual environment active, from the project root:

```bash
python backend/app.py
```

Then open **http://127.0.0.1:5000** in your browser.

- Flask serves both the website and the API at that address. Do **not** open the HTML files by double-clicking them, and do not use Live Server.
- If PowerShell blocks activation, you can skip it and call the environment's Python directly:
  ```powershell
  .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
  .\.venv\Scripts\python.exe backend/app.py
  ```
- A startup line beginning `WARNING: could not check/create database tables` means the app could not reach MySQL. Read the message after the colon and see [Troubleshooting](#9-troubleshooting).
- Stop the server with `Ctrl + C`.

---

## 8. Test that everything works

1. Open **Sign Up** and create a test account (password of at least 8 characters).
2. A 6-digit code arrives by email. The account is only created in `users` after you enter it.
3. Sign up again with the same email. You should see "That email already has an account" and no second row is created.
4. Log out and log in again. You get a login code by email too.
5. Check the data in MySQL:
   ```sql
   USE renthub_db;
   SELECT id, full_name, email, role, created_at FROM users;
   ```
   `password_hash` is a long hash. The real password is never stored.

---

## 9. Troubleshooting

| Problem | Likely cause and fix |
| --- | --- |
| `running scripts is disabled on this system` | Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, then activate again. |
| `'py' is not recognized` | Python is not installed or not on PATH. Reinstall it with **Add to PATH** ticked, or try `python` instead of `py`. |
| `ModuleNotFoundError: No module named 'flask'` (or `mysql`, `dotenv`) | The virtual environment is not active, or step 4 was skipped. Activate `.venv` and run `pip install -r backend/requirements.txt`. |
| `ERROR 1045 Access denied for user 'root'` | The password does not match. Make `DB_PASSWORD` equal to your MySQL root password (see 5.2). |
| `ERROR 1049 Unknown database 'renthub_db'` | The database does not exist yet. Run step 5.4. |
| `ERROR 2003 Can't connect to MySQL server` | MySQL is not running (step 5.1), or `DB_HOST` / `DB_PORT` are wrong. |
| `'mysql' is not recognized` | Add MySQL's `bin` folder to PATH, or run SQL from MySQL Workbench instead. |
| Sign-up says "Email sending is not set up", or the code email never arrives | `GMAIL_USER` / `GMAIL_APP_PASSWORD` are missing or wrong. You need a Google **App Password**, not the normal password. Check the spam folder too. |
| Port 5000 is already in use | Another program is using it (on macOS, AirPlay Receiver). Close it, or change the last line of `app.py` to `app.run(port=5001, debug=...)`. |
| Page loads but sign-up/login fails with a database error | Check the terminal running Flask; the real error is printed there. |

---

## 10. Moving existing data to another device

Cloning only copies the code. User accounts live in MySQL and profile photos live in `uploads/avatars/`, and neither is in Git. A new device starts with an empty database.

To carry your data over, on the **old** device:

```bash
mysqldump -u root -p --result-file=renthub_backup.sql renthub_db
```

(Use `--result-file` rather than `>` in Windows PowerShell, because `>` can save the file in an encoding MySQL cannot read.) Copy `renthub_backup.sql` and the `uploads/avatars/` folder to the new device. Then, on the **new** device, after creating the empty `renthub_db` (step 5.4):

```sql
USE renthub_db;
SOURCE renthub_backup.sql;
```

and put the avatar images back into `uploads/avatars/`.

---

## Project structure

```
RentHub/
├── backend/
│   ├── app.py              Flask server + API (register, login, 2FA, check-email, profile, logout)
│   └── requirements.txt    Python dependencies
├── database/
│   └── schema.sql          Creates renthub_db and its three tables
├── frontend/               The only folder Flask serves to the browser
│   ├── index.html
│   ├── pages/              browse, login, signup, myrentals, extendstay, profile
│   ├── css/                style.css, pages.css
│   ├── js/                 script.js
│   └── img/                images and logo
├── uploads/avatars/        Profile photos (created automatically, not in Git)
├── .env.example            Template for your private .env file
├── .gitignore
└── README.md
```

## Database tables

| Table | Purpose |
| --- | --- |
| `users` | Real accounts: name, unique email, password hash, role (tenant/landlord), phone, avatar, created date. |
| `login_codes` | The active 6-digit login code for a user, stored as a keyed hash. Valid for 10 minutes, 5 wrong guesses lock it. |
| `pending_signups` | Sign-ups waiting for their emailed code. The account moves into `users` only after the code is verified. |

## Notes and limitations

- **Two-factor codes:** both sign-up and login send a 6-digit code by Gmail. Codes expire after 10 minutes, 5 wrong guesses lock a code until a new one is requested, and "Resend code" has a 30-second cooldown.
- **Duplicate emails** are blocked in three layers: the sign-up form checks `GET /api/check-email`, `/api/register` rejects an existing email with HTTP 409, and the `UNIQUE` constraint on `users.email` stops it in the database itself.
- The sample rental listings and rental records are still in `frontend/js/script.js` and the browser's `localStorage`. They are **not yet stored in MySQL**, so they do not follow you to another device.
- This is a **local development** setup. Before any real deployment: turn debug mode off, use HTTPS, set a strong secret key, use a restricted MySQL user instead of `root`, and keep every password and key out of Git (use environment variables or `.env`).