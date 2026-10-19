# RentHub

RentHub is a website for finding rental places. It uses:
- **Python and Flask** for the backend (the part that handles requests and data).
- **MySQL** to store user account information.
- **HTML, CSS, and JavaScript** for the pages you see in your browser.

### Current features
- Create an account and log in using a 6-digit email code.
- Prevent two accounts from using the same email.
- Support tenant and landlord accounts.
- Edit your profile and upload a profile picture.

> **Important:** Rental listings and rental records are still sample data saved in the browser. They are not stored in MySQL yet.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Download the project](#2-download-the-project)
3. [Create a virtual environment](#3-create-a-virtual-environment)
4. [Install the required packages](#4-install-the-required-packages)
5. [Set up MySQL](#5-set-up-mysql)
6. [Set up email and private settings](#6-set-up-email-and-private-settings)
7. [Start RentHub](#7-start-renthub)
8. [Test the website](#8-test-the-website)
9. [Fix common problems](#9-fix-common-problems)
10. [Move your data to another computer](#10-move-your-data-to-another-computer)
11. [Project folders](#11-project-folders)
12. [Database tables and important notes](#12-database-tables-and-important-notes)

---

## 1. What you need

Install these tools first:

| Tool | Why you need it |
| --- | --- |
| **Git** | To download the project from GitHub. |
| **Python 3.10 or newer** | Runs the backend. |
| **MySQL Server 8.x** | Stores account information. |
| **MySQL Workbench** (optional) | Lets you run SQL using a visual interface. |
| **Internet connection** | Needed to install packages and send email codes. |

On Windows, when installing Python, select **Add Python to PATH**.

Check that the tools are installed by running these commands in your terminal:

```powershell
git --version
py --version
mysql --version
```

On macOS or Linux, use `python3 --version` instead of `py --version`.

If Windows says `mysql` is not recognized, MySQL may not be added to PATH. Its folder is often similar to:

`C:\Program Files\MySQL\MySQL Server 8.0\bin`

The version number may be different on your computer.

---

## 2. Download the project

Open a terminal and run:

```bash
git clone https://github.com/marcusgozon/RentHub.git
cd RentHub
```

Run the commands in the next sections from the main `RentHub` folder.

---

## 3. Create a virtual environment

A virtual environment keeps the Python packages for RentHub separate from other Python projects.

### Windows — PowerShell (such as the VS Code terminal)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says that script running is disabled, run this command once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then try activating the environment again.

### Windows — Command Prompt

```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it works, you should see `(.venv)` at the start of your terminal line.

Each time you open a new terminal, activate the environment again. You do not need to copy the `.venv` folder to another computer; create a new one there.

---

## 4. Install the required packages

Make sure your virtual environment is active, then run:

```bash
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

These commands install the Python packages RentHub needs, including:

- **Flask** — runs the website and backend routes.
- **mysql-connector-python** — lets Python connect to MySQL.
- **python-dotenv** — reads settings from a `.env` file.

To check the installed packages, run:

```bash
pip list
```

---

## 5. Set up MySQL

### 5.1 Start MySQL

On Windows:

1. Press `Win + R`.
2. Type `services.msc` and press Enter.
3. Find a service named something like `MySQL80`.
4. Make sure its status is **Running**.

You can also use PowerShell as an administrator:

```powershell
Get-Service *mysql*
net start MySQL80
```

On macOS with Homebrew, use `brew services start mysql`. On Linux, use `sudo systemctl start mysql`.

### 5.2 Check the database settings

RentHub needs the correct MySQL connection details. The app reads these from `backend/app.py`, and a `.env` file can override them.

| Setting | Usual value | What it means |
| --- | --- | --- |
| `DB_HOST` | `localhost` | MySQL is on your computer. |
| `DB_PORT` | `3306` | MySQL's port. |
| `DB_USER` | `root` | The MySQL account used by the app. |
| `DB_PASSWORD` | Your configured password | Must match the MySQL account password. |
| `DB_NAME` | `renthub_db` | The database RentHub uses. |

Your settings must match your MySQL setup. You can either update the settings in `app.py` or create a `.env` file as explained in section 6.

**Security tip:** For a real deployment, do not use the MySQL `root` account for your website. Create a separate account with access only to the RentHub database.

### 5.3 Test your MySQL login

Run:

```bash
mysql -u root -p
```

Enter your MySQL password. If you see the `mysql>` prompt, you are connected.

If you get an access-denied error, check that the username and password are correct.

### 5.4 Create the database

At the `mysql>` prompt, run:

```sql
CREATE DATABASE IF NOT EXISTS renthub_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 5.5 Create the tables

RentHub uses four tables: `users`, `login_codes`, `pending_signups`, and `user_avatars`. The `users` table stores each user’s phone number and avatar reference. The `user_avatars` table stores the actual profile image.

You can run the SQL below, or open `database/schema.sql` and execute it in MySQL Workbench.

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

CREATE TABLE IF NOT EXISTS login_codes (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    code_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_login_codes_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

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

-- Store profile image data in a separate table.
CREATE TABLE IF NOT EXISTS user_avatars (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    mime_type VARCHAR(50) NOT NULL,
    image MEDIUMBLOB NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT fk_user_avatars_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### Ways to run the SQL

**Option A — MySQL command line**

From the MySQL prompt, run:

```sql
SOURCE database/schema.sql;
```

If MySQL cannot find the file, use its full path, with forward slashes. For example:

```sql
SOURCE C:/Users/you/RentHub/database/schema.sql;
```

**Option B — MySQL Workbench**

1. Open MySQL Workbench and connect to your server.
2. Choose **File > Open SQL Script**.
3. Open `database/schema.sql`.
4. Click the lightning bolt to run the script.

**Option C — Let RentHub create missing tables**

The backend calls `ensure_schema()` when it starts. It can create missing tables if the `renthub_db` database already exists and MySQL is reachable.

**Windows PowerShell note:** The command `mysql -u root -p < database/schema.sql` may not work in PowerShell. Use one of the options above instead.

### 5.6 Check that the tables exist

Run:

```sql
USE renthub_db;
SHOW TABLES;
DESCRIBE users;
```

You should see `users`, `login_codes`, `pending_signups`, and `user_avatars`.

To confirm the user profile columns, run:

```sql
SELECT id, full_name, phone, avatar FROM users;
```

If your existing `users` table does **not** have a `phone` column, run this once. Skip it if the column already exists:

```sql
ALTER TABLE users ADD COLUMN phone VARCHAR(20) NULL;
```

> **Important:** `CREATE TABLE IF NOT EXISTS` does not change existing tables. Check existing columns before running `ALTER TABLE`, or MySQL may report a duplicate-column error.

### 5.7 Optional: create a separate MySQL account for RentHub

This is safer than using `root`:

```sql
CREATE USER 'renthub'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON renthub_db.* TO 'renthub'@'localhost';
FLUSH PRIVILEGES;
```

Change `DB_USER` and `DB_PASSWORD` in your `.env` file or app settings to match this account.

---

## 6. Set up email and private settings

You can use a `.env` file to store your passwords and other private settings outside your Python code. Do not upload this file to GitHub.

From the main project folder, create your `.env` file by copying the example:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS or Linux

```bash
cp .env.example .env
```

Open `.env` and enter your own values:

```ini
DB_PASSWORD=your-mysql-password

RENTHUB_SECRET_KEY=put-a-long-random-secret-here

GMAIL_USER=your-sending-gmail@gmail.com
GMAIL_APP_PASSWORD=your-16-character-google-app-password
```

You can also set `DB_HOST`, `DB_PORT`, `DB_USER`, and `DB_NAME` if you need different values.

### Gmail setup

To send verification codes through Gmail:

1. Sign in to the Google account that will send the codes.
2. Turn on 2-Step Verification.
3. Open Google Account settings and create an **App Password**.
4. Put that App Password in `GMAIL_APP_PASSWORD`.

Use the App Password, not your normal Gmail password.

Keep the same `RENTHUB_SECRET_KEY` between restarts. To generate a random one, run:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Create a new `.env` file on each computer. Do not share your real passwords or secret keys.

---

## 7. Start RentHub

Make sure:
- MySQL is running.
- The `renthub_db` database exists.
- Your `.env` settings (if used) are correct.
- Your virtual environment is active.

From the main `RentHub` folder, run:

```bash
python backend/app.py
```

Then open this address in your browser:

**http://127.0.0.1:5000**

Flask serves both the website and its API. **Do not open the HTML files by double-clicking them or use VS Code Live Server** for this setup.

If PowerShell makes it difficult to activate the environment, you can run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe backend/app.py
```

If the terminal says it cannot connect to MySQL or create the tables, check the error message and use the troubleshooting section below.

To stop RentHub, press `Ctrl + C` in the terminal.

---

## 8. Test the website

After RentHub starts:

1. Open the **Sign Up** page.
2. Create a test account with a password of at least 8 characters.
3. Check your email for the 6-digit verification code.
4. Enter the code. The account should then be saved in `users`.
5. Try signing up again with the same email. RentHub should block the duplicate.
6. Log out and log in again. You should receive another verification code.

You can check registered accounts in MySQL:

```sql
USE renthub_db;
SELECT id, full_name, email, role, created_at FROM users;
```

The database stores a password hash, not the original password.

---

## 9. Fix common problems

| Problem | What to try |
| --- | --- |
| PowerShell says script running is disabled | Follow the instructions in section 3. |
| `py` is not recognized | Install Python and select **Add Python to PATH**. You can also try `python`. |
| `No module named flask`, `mysql`, or `dotenv` | Activate `.venv` and run `pip install -r backend/requirements.txt`. |
| MySQL says access denied | Check `DB_USER` and `DB_PASSWORD`. |
| `Unknown database 'renthub_db'` | Follow section 5.4 to create the database. |
| Cannot connect to MySQL | Make sure MySQL is running and check `DB_HOST` and `DB_PORT`. |
| `mysql` is not recognized | Add MySQL's `bin` folder to PATH, or use MySQL Workbench. |
| Verification email does not arrive | Check `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and your spam folder. Use a Gmail App Password. |
| Port 5000 is already in use | Close the other program using it, or change the port in the app's run settings. |
| The page opens, but sign-up or login fails | Read the error shown in the terminal where Flask is running. |

---

## 10. Move your data to another computer

Downloading the project does **not** copy your database or uploaded profile photos. You need to back them up separately.

### On the old computer

Run:

```bash
mysqldump -u root -p --result-file=renthub_backup.sql renthub_db
```

Copy `renthub_backup.sql` and the `uploads/avatars/` folder to the new computer.

### On the new computer

1. Install the required tools.
2. Follow the setup steps above.
3. Create the `renthub_db` database.
4. Import the backup from the MySQL prompt:

```sql
USE renthub_db;
SOURCE C:/path/to/renthub_backup.sql;
```

Replace the example path with the real location of your backup file. Restore the avatar images to `uploads/avatars/` as well.

---

## 11. Project folders

```text
RentHub/
├── backend/
│   ├── app.py              Flask backend and API
│   └── requirements.txt    Python packages needed
├── database/
│   └── schema.sql          SQL for creating the database tables
├── frontend/
│   ├── index.html          Main page
│   ├── pages/              Website pages
│   ├── css/                Website styles
│   ├── js/                 JavaScript files
│   └── img/                Images and logo
├── uploads/
│   └── avatars/            Uploaded profile pictures
├── .env.example            Example private settings
├── .gitignore              Files Git should ignore
└── README.md               This guide
```

---

## 12. Database tables and important notes

### What the tables store

| Table | What it is for |
| --- | --- |
| `users` | Registered users, their names, emails, roles, and profile details. |
| `login_codes` | Login verification codes stored as hashes. |
| `pending_signups` | Sign-ups waiting for email verification. |
| `user_avatars` | Stores profile image data and links it to a user. |

### Current limits

- Sign-up and login use a 6-digit code sent through Gmail.
- Codes expire after 10 minutes. Five incorrect attempts lock a code until a new one is requested. Resending a code has a 30-second wait.
- RentHub blocks duplicate email addresses through the website and database.
- Rental listings and rental records are still sample data in `frontend/js/script.js` and the browser's `localStorage`. They are **not saved in MySQL yet**.
- This setup is for local development, not a finished public website.

### Before putting RentHub online

- Turn off Flask debug mode.
- Use HTTPS.
- Use a strong secret key.
- Use a separate MySQL account instead of `root`.
- Keep passwords and secret keys out of GitHub.
- Store private settings in environment variables or `.env`.
