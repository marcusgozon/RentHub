# RentHub: Flask + MySQL starter

This version connects your existing HTML/CSS/JavaScript website to a Python Flask backend and MySQL database for account registration and login.

## Folder structure

```
RentHub/
├── backend/
│   ├── app.py              Flask server + API (register, login, 2FA, check-email, logout)
│   └── requirements.txt
├── database/
│   └── schema.sql          Creates renthub_db and the users table
├── frontend/               The only folder Flask serves to the browser
│   ├── index.html
│   ├── pages/              browse, login, signup, myrentals, extendstay
│   ├── css/                style.css, pages.css
│   ├── js/                 script.js
│   └── img/                herobg.jpg, renthub_logo.png
├── .env.example
├── .gitignore
└── README.md
```

The `.venv/` folder is **not** part of the project. It is created on your machine by the
install step below and is listed in `.gitignore`, so never copy or zip it.

## 1. Create the database

1. Open MySQL Workbench and connect to your local MySQL server.
2. Open `database/schema.sql`.
3. Click the lightning bolt (Execute).
4. Confirm `renthub_db` and its `users` table appear under Schemas.

The database stores a full name, unique email, password hash, role (tenant/landlord), and account creation date. It does **not** store a plain-text password.

## 2. Configure your secrets (`.env`)

Secrets are read from a `.env` file in the project root, loaded automatically when the server starts. No `$env:` commands needed.

1. Copy `.env.example` to `.env`.
2. Fill in `DB_PASSWORD`, `RENTHUB_SECRET_KEY`, `GMAIL_USER` and `GMAIL_APP_PASSWORD`.

`DB_HOST`, `DB_PORT`, `DB_USER` and `DB_NAME` default to `localhost`, `3306`, `root` and `renthub_db`, so only change them if yours differ.

`.env` is listed in `.gitignore` and is never pushed to GitHub. **On a new device, clone the repo, copy your `.env` file into the project root, and continue from step 3.** Real environment variables, if set, override the file.

## 3. Install and run the backend

Open VS Code terminal at the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
python backend/app.py
```

If PowerShell blocks activation, you can run the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe backend/app.py
```

Open **http://127.0.0.1:5000**. Do not open the HTML by double-clicking it or use Live Server for this backend-connected version. Flask serves the website and API on the same address.

## 4. Test it

1. Open Sign Up and create a test account.
2. Use a password of at least 8 characters.
3. After you submit the sign-up form you should receive a 6-digit code by email. The account only appears in `users` after you enter it.
4. Try signing up again with the same email. You should see "That email already has an account." and no second row is created.
5. Try logging out and logging back in (you will get a login code too).
6. In MySQL Workbench, refresh `renthub_db` > Tables > `users`, then select the table and view its rows. The `password_hash` column should look like a long hash, not your actual password.

## Important current limitations

- The signup/login account information is now stored in MySQL and password hashes are used.
- Existing sample rental listings and rental records are still in `frontend/js/script.js` / browser `localStorage`. They are **not yet stored in MySQL**.
- The current rental actions are a front-end demo. Before real use, rental APIs must check the logged-in user on the server and enforce tenant/landlord permissions.
- This is for local development. Before deployment, turn debug mode off, use HTTPS, set a strong secret key, and use a restricted MySQL user instead of `root`.

## Duplicate email protection

Registration is blocked for an email that already has an account, in three layers:

1. **Signup form**: when you leave the email field, the page calls `GET /api/check-email` and shows a warning right away.
2. **`email_exists()` in `backend/app.py`**: `/api/register` checks it before inserting. Emails are trimmed and lower-cased, so `Juan@Mail.com` and `juan@mail.com` are the same account. It returns HTTP 409.
3. **`UNIQUE` constraint on `users.email`**: the database itself rejects a duplicate even if two signups happen at the same instant.

## Two-factor codes (sign-up and login, 6 digits by Gmail)

The server emails a 6-digit code in two places, and uses the same Gmail setup for both:

- **Sign-up:** the account is **not created** until the emailed code is entered. Until then the details wait in the `pending_signups` table, so nobody can register an email address they don't own.
- **Login:** after a correct email and password, the user is only logged in once they enter the code.

**One-time setup**

1. Re-run `database/schema.sql` in MySQL Workbench. It is safe to re-run and adds the `login_codes` and `pending_signups` tables.
2. In the Google account that will *send* the emails, turn on 2-Step Verification, then create an App password (Google Account > Security > App passwords).
3. Put the sender details in your `.env` file (`GMAIL_USER` and `GMAIL_APP_PASSWORD`), then start the server as usual. Never put the app password in code, in this README, or in Git. If it leaks, delete it in your Google account and create a new one.

**How it works**

- The code is random, valid for 10 minutes, and stored only as a keyed hash.
- 5 wrong guesses lock the code until a new one is requested. "Resend code" has a 30-second cooldown, which also stops the sign-up form being used to flood someone's inbox.
- If Gmail fails (wrong app password, etc.) nothing is saved, so the user can simply try again.
- A user who has not entered the code has no session, so protected actions stay locked.
