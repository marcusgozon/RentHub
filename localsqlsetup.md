Your SQL is almost correct. You just need to select the `renthub_db` database before creating the `users` table.

```
USE renthub_db;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'manager', 'user') DEFAULT 'user' NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### How to run it in MySQL

1. Make sure the `renthub_db` database already exists.
2. Open MySQL Workbench or your MySQL terminal.
3. Paste and execute the SQL code.
4. Check whether the table was created:

```
SHOW TABLES;
DESCRIBE users;
```

If you haven't created the database yet, run this first:

```
CREATE DATABASE renthub_db;
USE renthub_db;
```

### What the `users` table stores

| Column          | Purpose                                  |
| --------------- | ---------------------------------------- |
| `id`            | Unique ID for each user                  |
| `full_name`     | User's full name                         |
| `email`         | Unique email address                     |
| `password_hash` | Securely hashed password, not plain text |
| `role`          | User permission: admin, manager, or user |
| `created_at`    | Date and time the account was created    |

For your RentHub website: Since you're building a rental system, you may eventually want roles such as `tenant` and `landlord` instead of `manager` and `user`. Also, your Python backend should hash passwords before storing them in MySQL.
