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