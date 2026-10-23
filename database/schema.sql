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

-- Password reset codes: one active reset per email. The new password is stored
-- only after the verification code is entered successfully.
CREATE TABLE IF NOT EXISTS password_resets (
    email VARCHAR(255) NOT NULL PRIMARY KEY,
    code_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_password_resets_user FOREIGN KEY (email) REFERENCES users(email) ON DELETE CASCADE
);

-- Homes posted by landlords.
CREATE TABLE IF NOT EXISTS listings (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    landlord_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(120) NOT NULL,
    location VARCHAR(160) NOT NULL,
    type ENUM('Studio', 'Condo', 'Apartment', 'House', 'Bedspace') NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    beds TINYINT UNSIGNED NOT NULL DEFAULT 0,
    baths TINYINT UNSIGNED NOT NULL DEFAULT 1,
    description TEXT NULL,
    status ENUM('available', 'rented', 'unavailable') NOT NULL DEFAULT 'available',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_listings_landlord (landlord_id),
    CONSTRAINT fk_listings_landlord FOREIGN KEY (landlord_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Listing photos are stored in the database, like profile photos. The token is the public URL key.
CREATE TABLE IF NOT EXISTS listing_images (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    listing_id BIGINT UNSIGNED NOT NULL,
    token CHAR(32) NOT NULL UNIQUE,
    data MEDIUMBLOB NOT NULL,
    mime VARCHAR(30) NOT NULL,
    sort_order TINYINT UNSIGNED NOT NULL DEFAULT 0,
    KEY idx_listing_images_listing (listing_id),
    CONSTRAINT fk_listing_images_listing FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE
);

-- Rental requests act as in-app notifications for both parties: landlords see
-- pending requests, and tenants see the landlord's decision and payment status.
CREATE TABLE IF NOT EXISTS rental_requests (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    listing_id BIGINT UNSIGNED NOT NULL,
    tenant_id BIGINT UNSIGNED NOT NULL,
    move_in DATE NOT NULL,
    months TINYINT UNSIGNED NOT NULL,
    monthly_price DECIMAL(10, 2) NOT NULL,
    status ENUM('pending', 'approved', 'rejected', 'paid') NOT NULL DEFAULT 'pending',
    payment_method VARCHAR(80) NULL,
    payment_reference VARCHAR(100) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    paid_at TIMESTAMP NULL,
    KEY idx_rental_requests_listing (listing_id, status),
    KEY idx_rental_requests_tenant (tenant_id, created_at),
    CONSTRAINT fk_rental_requests_listing FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE,
    CONSTRAINT fk_rental_requests_tenant FOREIGN KEY (tenant_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Tenant reviews: one review per tenant per listing.
CREATE TABLE IF NOT EXISTS reviews (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    listing_id BIGINT UNSIGNED NOT NULL,
    tenant_id BIGINT UNSIGNED NOT NULL,
    rating TINYINT UNSIGNED NOT NULL,
    comment VARCHAR(1000) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_review_once (listing_id, tenant_id),
    CONSTRAINT chk_review_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT fk_reviews_listing FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE,
    CONSTRAINT fk_reviews_tenant FOREIGN KEY (tenant_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Tenants a landlord manages. user_email (optional) links the record to a tenant's RentHub account,
-- so that tenant can see and pay their own bills.
CREATE TABLE IF NOT EXISTS tenants (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    landlord_id BIGINT UNSIGNED NOT NULL,
    listing_id BIGINT UNSIGNED NULL,
    user_email VARCHAR(255) NULL,
    name VARCHAR(100) NOT NULL,
    unit VARCHAR(160) NOT NULL,
    rent DECIMAL(10, 2) NOT NULL,
    status ENUM('Active', 'Inactive') NOT NULL DEFAULT 'Active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_tenants_landlord (landlord_id),
    KEY idx_tenants_listing (listing_id),
    KEY idx_tenants_email (user_email),
    CONSTRAINT fk_tenants_landlord FOREIGN KEY (landlord_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_tenants_listing FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE SET NULL
);

-- Monthly bills. "Overdue" is not stored: it is an Unpaid bill whose due date has passed.
CREATE TABLE IF NOT EXISTS bills (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    landlord_id BIGINT UNSIGNED NOT NULL,
    tenant_id BIGINT UNSIGNED NOT NULL,
    month CHAR(7) NOT NULL,
    rent DECIMAL(10, 2) NOT NULL,
    extra DECIMAL(10, 2) NOT NULL DEFAULT 0,
    total DECIMAL(10, 2) NOT NULL,
    due_date DATE NOT NULL,
    status ENUM('Unpaid', 'Pending', 'Paid') NOT NULL DEFAULT 'Unpaid',
    reference VARCHAR(100) NULL,
    paid_on DATE NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bill_month (tenant_id, month),
    KEY idx_bills_landlord (landlord_id),
    CONSTRAINT fk_bills_landlord FOREIGN KEY (landlord_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_bills_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);
