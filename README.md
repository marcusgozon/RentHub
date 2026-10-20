# RentHub

RentHub is a website for finding places to rent. It is built with:

- **Python and Flask** for the backend (the part that handles requests and saves data).
- **MySQL** to save user accounts and profile photos.
- **HTML, CSS, and JavaScript** for the pages you see in your browser.

### What it can do now

- Sign up and log in with a 6-digit code sent to your email.
- Stop two accounts from using the same email.
- Two account types: tenant and landlord.
- Edit your profile (mobile number) and upload a profile picture. Photos are saved inside the MySQL database, not as loose files in the project folder.
- A loading screen: the RentHub logo fades in and out when you change pages.
- A new home page with an intro (headline, short text, and quick links) next to the search card.
- A smaller desktop layout (80% size). Phones keep the normal size.
- A show/hide button on password boxes, and a mobile menu that slides in from the side.

> **Important:** Rental listings and rental records are still sample data saved in your browser. They are **not** saved in MySQL yet.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Download the project](#2-download-the-project)
3. [Create a virtual environment](#3-create-a-virtual-environment)
4. [Install the packages](#4-install-the-packages)
5. [Set up MySQL](#5-set-up-mysql)
6. [Set up email and private settings](#6-set-up-email-and-private-settings)
7. [Start RentHub](#7-start-renthub)
8. [Test the website](#8-test-the-website)
9. [Fix common problems](#9-fix-common-problems)
10. [Move your data to another computer](#10-move-your-data-to-another-computer)
11. [Project folders](#11-project-folders)
12. [Database tables and notes](#12-database-tables-and-notes)
13. [Website pages and how to change them](#13-website-pages-and-how-to-change-them)

---

## 1. What you need

Install these first:

| Tool | Why you need it |
| --- | --- |
| **Git** | Downloads the project from GitHub. |
| **Python 3.10 or newer** | Runs the backend. |
| **MySQL Server 8.x** | Saves the accounts and photos. |
| **MySQL Workbench** (optional) | Lets you run SQL with buttons and windows instead of typing in a terminal. |
| **Internet** | Needed to install packages and send email codes. |

On Windows, when you install Python, tick **Add Python to PATH**.

To check that everything is installed, run these in your terminal:

```powershell
git --version
py --version
mysql --version
```

On macOS or Linux, use `python3 --version` instead of `py --version`.

If Windows says `mysql` is not recognized, MySQL may not be in PATH. Its folder usually looks like this:

`C:\Program Files\MySQL\MySQL Server 8.0\bin`

The version number on your computer may be different.

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

A virtual environment keeps RentHub's Python packages apart from your other Python projects.

### Windows: PowerShell (like the VS Code terminal)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says running scripts is turned off, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then try to activate it again.

### Windows: Command Prompt

```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it works, you will see `(.venv)` at the start of your terminal line.

Each time you open a new terminal, activate the environment again. Do not copy the `.venv` folder to another computer. Make a new one there.

---

## 4. Install the packages

Make sure your virtual environment is active, then run:

```bash
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

This installs the Python packages RentHub needs, such as:

- **Flask** runs the website and the backend.
- **mysql-connector-python** lets Python talk to MySQL.
- **python-dotenv** reads your settings from a `.env` file.

To see the installed packages, run:

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
4. Make sure its status says **Running**.

You can also use PowerShell as administrator:

```powershell
Get-Service *mysql*
net start MySQL80
```

On macOS with Homebrew, run `brew services start mysql`. On Linux, run `sudo systemctl start mysql`.

### 5.2 Check the database settings

RentHub needs your MySQL login details. It reads them from `backend/app.py`, and a `.env` file can replace them.

| Setting | Usual value | What it means |
| --- | --- | --- |
| `DB_HOST` | `localhost` | MySQL is on your own computer. |
| `DB_PORT` | `3306` | The port MySQL uses. |
| `DB_USER` | `root` | The MySQL account the app uses. |
| `DB_PASSWORD` | Your own password | Must be the same as your MySQL account password. |
| `DB_NAME` | `renthub_db` | The database RentHub uses. |

These must match your MySQL. You can change them in `app.py` or in a `.env` file (see section 6).

**Safety tip:** If you put RentHub online, do not use the `root` account. Make a separate account that can only use the RentHub database.

### 5.3 Test your MySQL login

Run:

```bash
mysql -u root -p
```

Type your MySQL password. If you see the `mysql>` prompt, you are connected.

If you see an "access denied" error, check your username and password.

### 5.4 Create the database

At the `mysql>` prompt, run:

```sql
CREATE DATABASE IF NOT EXISTS renthub_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 5.5 Create the tables

RentHub uses three tables: `users`, `login_codes`, and `pending_signups`.

The `users` table also keeps each person's phone number and profile photo. The photo is saved right inside the table, in these columns:

| Column | What it holds |
| --- | --- |
| `avatar` | A random code (token) used in the photo's web address. It is **not** the picture. |
| `avatar_data` | The picture itself (the raw image bytes). |
| `avatar_mime` | The picture type, such as `image/jpeg`. |

You can run the SQL below, or open `database/schema.sql` in MySQL Workbench and run it.

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
    avatar_data MEDIUMBLOB NULL,
    avatar_mime VARCHAR(30) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Login codes: one code per user. Only a hash is saved, never the code itself.
CREATE TABLE IF NOT EXISTS login_codes (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    code_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_login_codes_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Sign-ups that are waiting for the email code.
-- The real account is only made in `users` after the code is correct.
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

### Ways to run the SQL

**Option A: MySQL command line**

At the MySQL prompt, run:

```sql
SOURCE database/schema.sql;
```

If MySQL cannot find the file, use the full path with forward slashes, like this:

```sql
SOURCE C:/Users/you/RentHub/database/schema.sql;
```

**Option B: MySQL Workbench**

1. Open MySQL Workbench and connect to your server.
2. Click **File > Open SQL Script**.
3. Pick `database/schema.sql`.
4. Click the lightning bolt button to run it.

**Option C: Let RentHub do it**

When RentHub starts, it runs `ensure_schema()`. This makes any missing tables and adds any missing columns by itself. It only works if the `renthub_db` database already exists and MySQL is running.

**Windows PowerShell note:** `mysql -u root -p < database/schema.sql` may not work in PowerShell. Use option A, B, or C instead.

### 5.6 Check that the tables exist

Run:

```sql
USE renthub_db;
SHOW TABLES;
DESCRIBE users;
```

You should see `users`, `login_codes`, and `pending_signups`.

To see the users and their phone numbers, run:

```sql
SELECT id, full_name, phone, avatar FROM users;
```

> **Note:** `CREATE TABLE IF NOT EXISTS` does not change a table that already exists. If your old `users` table is missing a column, just start RentHub. It adds the missing columns for you (`phone`, `avatar`, `avatar_data`, `avatar_mime`).

#### Check and view a saved profile photo in MySQL Workbench

Remember: the `avatar` column is only a random code. The real picture is in `avatar_data`. So if you only select `avatar`, you will never see the photo.

**Step 1: See who has a photo.** This shows the code, the picture type, and the size in bytes. It does not show the picture. A number in `bytes` means a photo is saved. `NULL` means no photo.

```sql
USE renthub_db;
SELECT id, full_name, avatar, avatar_mime, LENGTH(avatar_data) AS bytes FROM users;
```

**Step 2: Get the picture of one user.** Change the `id` to the user you want.

```sql
SELECT id, full_name, avatar_data FROM users WHERE id = 1;
```

**Step 3: Open the picture in Workbench.**

1. In the result table, find the `avatar_data` cell. It says `BLOB`.
2. Right-click the cell and choose **Open Value in Editor**. You can also click the cell and then click the small blob icon.
3. In the window that opens, click the **Image** tab to see the photo.
4. Optional: click **Save...** to save the photo as a `.jpg`, `.png`, or `.webp` file.

If the **Image** tab is missing or empty, click the **Binary** tab. Also check that this option is turned **off**: **Edit > Preferences > SQL Editor > Treat BINARY/VARBINARY as nonbinary character string**.

**Step 4 (other way): See the photo in your browser.** Start RentHub, then open this address. Replace `<token>` with the value from the `avatar` column. Replace `5000` if RentHub uses a different port.

```
http://localhost:5000/api/avatar/<token>
```

### 5.7 Optional: make a separate MySQL account for RentHub

This is safer than using `root`:

```sql
CREATE USER 'renthub'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON renthub_db.* TO 'renthub'@'localhost';
FLUSH PRIVILEGES;
```

Then change `DB_USER` and `DB_PASSWORD` in your `.env` file or app settings to match.

---

## 6. Set up email and private settings

A `.env` file keeps your passwords and other private settings out of your Python code. Never upload this file to GitHub.

In the main project folder, copy the example file to make your own `.env`:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### macOS or Linux

```bash
cp .env.example .env
```

Open `.env` and type in your own values:

```ini
DB_PASSWORD=your-mysql-password

RENTHUB_SECRET_KEY=put-a-long-random-secret-here

GMAIL_USER=your-sending-gmail@gmail.com
GMAIL_APP_PASSWORD=your-16-character-google-app-password
```

You can also set `DB_HOST`, `DB_PORT`, `DB_USER`, and `DB_NAME` if yours are different.

### Gmail setup

To send the email codes with Gmail:

1. Sign in to the Google account that will send the codes.
2. Turn on 2-Step Verification.
3. Open your Google Account settings and make an **App Password**.
4. Put that App Password in `GMAIL_APP_PASSWORD`.

Use the App Password, not your normal Gmail password.

Keep the same `RENTHUB_SECRET_KEY` every time you restart. To make a random one, run:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Make a new `.env` file on each computer. Never share your real passwords or secret keys.

---

## 7. Start RentHub

Before you start, make sure:

- MySQL is running.
- The `renthub_db` database exists.
- Your `.env` settings are correct (if you use one).
- Your virtual environment is active.

From the main `RentHub` folder, run:

```bash
python backend/app.py
```

Then open this address in your browser:

**http://127.0.0.1:5000**

Flask runs both the website and its backend. **Do not double-click the HTML files and do not use VS Code Live Server.** They will not work with this setup.

If PowerShell will not let you activate the environment, you can use the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe backend/app.py
```

If the terminal says it cannot connect to MySQL or cannot make the tables, read the error and look at section 9.

To stop RentHub, press `Ctrl + C` in the terminal.

---

## 8. Test the website

After RentHub starts:

1. Open the **Sign Up** page.
2. Make a test account. The password must have at least 8 characters.
3. Check your email for the 6-digit code.
4. Type in the code. The account is now saved in `users`.
5. Try to sign up again with the same email. RentHub should say no.
6. Log out, then log in again. You get a new code.
7. Open the **Profile** page (the profile icon at the top). Add a mobile number and upload a JPG, PNG, or WEBP photo under 2 MB. The photo shows in the top icon.
8. Restart RentHub and log in again. The photo is still there, because it is saved in MySQL.
9. Click between pages. You should briefly see the RentHub logo loading screen.

To see the accounts in MySQL:

```sql
USE renthub_db;
SELECT id, full_name, email, role, created_at FROM users;
```

The database saves a password hash, not the real password.

---

## 9. Fix common problems

| Problem | What to try |
| --- | --- |
| PowerShell says running scripts is turned off | Follow the steps in section 3. |
| `py` is not recognized | Install Python and tick **Add Python to PATH**. You can also try `python`. |
| `No module named flask`, `mysql`, or `dotenv` | Activate `.venv`, then run `pip install -r backend/requirements.txt`. |
| MySQL says access denied | Check `DB_USER` and `DB_PASSWORD`. |
| `Unknown database 'renthub_db'` | Make the database (section 5.4). |
| Cannot connect to MySQL | Make sure MySQL is running. Check `DB_HOST` and `DB_PORT`. |
| `mysql` is not recognized | Add MySQL's `bin` folder to PATH, or use MySQL Workbench. |
| The email code does not arrive | Check `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and your spam folder. Use a Gmail App Password. |
| Port 5000 is already used | Close the other program that uses it, or change the port in the app's run settings. |
| The page opens, but sign-up or login fails | Read the error in the terminal where Flask is running. |
| A photo does not show in Workbench | Use the steps in section 5.6. Open the `avatar_data` cell in the **Image** tab. |

---

## 10. Move your data to another computer

Downloading the project does **not** copy your database. Accounts **and profile photos** are both in MySQL, so one backup copies everything. You do not need to copy any photo folder.

### On the old computer

Run:

```bash
mysqldump -u root -p --result-file=renthub_backup.sql renthub_db
```

Copy `renthub_backup.sql` to the new computer. The file can be big because it includes the photos.

### On the new computer

1. Install the tools you need (section 1).
2. Follow the setup steps above.
3. Make the `renthub_db` database.
4. Load the backup at the MySQL prompt:

```sql
USE renthub_db;
SOURCE C:/path/to/renthub_backup.sql;
```

Change the example path to the real place of your backup file. The photos come back together with the accounts.

---

## 11. Project folders

```text
RentHub/
├── backend/
│   ├── app.py              Flask backend and API
│   └── requirements.txt    Python packages needed
├── database/
│   └── schema.sql          SQL that makes the database tables
├── frontend/
│   ├── index.html          Main page
│   ├── pages/              Website pages (login, sign up, browse, my rentals, extend stay, profile)
│   ├── css/                Website styles
│   ├── js/                 JavaScript files
│   └── img/                Images and logo
├── .env.example            Example private settings
├── .gitignore              Files Git should ignore
└── README.md               This guide
```

---

## 12. Database tables and notes

### What each table is for

| Table | What it is for |
| --- | --- |
| `users` | Registered users: name, email, role, phone number, and profile photo. |
| `login_codes` | Login codes (saved as hashes). |
| `pending_signups` | Sign-ups waiting for the email code. |

### Limits right now

- Sign-up and login use a 6-digit code sent through Gmail.
- A code lasts 10 minutes. After 5 wrong tries, the code is locked until you ask for a new one. After you ask to resend a code, you must wait 30 seconds.
- RentHub blocks the same email twice, both in the website and in the database.
- Profile photos must be JPG, PNG, or WEBP and no bigger than 2 MB. RentHub checks what is really inside the file, not just its name.
- Rental listings and rental records are still sample data in `frontend/js/script.js` and in the browser's `localStorage`. They are **not saved in MySQL yet**.
- This setup is for working on your own computer. It is not ready to be a public website.

### Before you put RentHub online

- Turn off Flask debug mode.
- Use HTTPS.
- Use a strong secret key.
- Use a separate MySQL account, not `root`.
- Keep passwords and secret keys out of GitHub.
- Keep private settings in environment variables or in `.env`.

---

## 13. Website pages and how to change them

These parts are plain HTML, CSS, and JavaScript. You do not need to restart RentHub. Just refresh the page after you change a file. If you do not see the change, press `Ctrl + F5`.

### Page loading screen

A cream-colored screen with the moving RentHub logo covers the page while it loads, and when you click a link to another page.

- The HTML (`<div class="page-loader">`) is right after `<body>` on every page.
- Its styles are at the bottom of `frontend/css/style.css`. Search for `Page loader`.
- Its code is in `frontend/js/script.js`. Search for `Page loader`. Two numbers control the timing: `MIN_SHOW` (the shortest time it stays, in milliseconds) and the wait before going to the next page.
- It does not show for links to other websites, links that open in a new tab, and `#anchor` links on the same page.
- If a person's device is set to reduce motion, they see a still logo instead of the moving one.

If you add a new page, copy the `page-loader` block from any other page into it, so the loading screen shows there too.

### Home page intro

The text next to the search card (headline, short text, two buttons, and two small info cards) is in the `hero-copy` block in `frontend/index.html`. Change the words there. Its styles are in `frontend/css/style.css` under `Hero intro text`. On phones, the text sits above the search card and the two small info cards are hidden.

### Desktop size (80%)

On screens wider than 760 px, the whole site shows at 80%, like a browser zoomed out to 80%. This comes from one rule near the top of `frontend/css/style.css`:

```css
@media (min-width: 761px) {
  html { font-size: 80%; }
}
```

Change `80%` to `75%` to make everything smaller, or to `85%` to make it bigger. The styles use `rem` units, so everything changes size together. For new sizes, use `rem` (not `px`) so they follow the same scale. Thin borders of 2 px or less stay in `px` on purpose.