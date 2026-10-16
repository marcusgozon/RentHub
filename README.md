# RentHub: Flask + MySQL starter

This version connects your existing HTML/CSS/JavaScript website to a Python Flask backend and MySQL database for account registration and login.

## Folder structure

```
RentHub/
├── backend/
│   ├── app.py              Flask server + API (register, login, check-email, logout)
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

## 2. Configure the MySQL connection

The app (`backend/app.py`) reads these environment variables:
- `DB_HOST` (default `localhost`)
- `DB_PORT` (default `3306`)
- `DB_USER` (default `root`)
- `DB_PASSWORD` (your local MySQL password)
- `DB_NAME` (default `renthub_db`)

In Windows PowerShell, from the project root, set them for the current terminal session (replace the example password):

```powershell
$env:DB_HOST="localhost"
$env:DB_PORT="3306"
$env:DB_USER="root"
$env:DB_PASSWORD="YOUR_MYSQL_PASSWORD"
$env:DB_NAME="renthub_db"
$env:RENTHUB_SECRET_KEY="replace-this-with-a-long-random-secret"
```

Do not share or commit your real password or secret key. If you prefer a `.env` file, install `python-dotenv` and load it in `app.py`; this starter intentionally uses environment variables directly.

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
3. Try signing up again with the same email. You should see "That email already has an account." and no second row is created.
4. Try logging out and logging back in.
5. In MySQL Workbench, refresh `renthub_db` > Tables > `users`, then select the table and view its rows. The `password_hash` column should look like a long hash, not your actual password.

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
