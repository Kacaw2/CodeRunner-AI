-- init.sql
-- Database initialization script for MySQL container

-- Set timezone and charset
SET time_zone = '+10:00';
SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS coderunner CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Switch to the database
USE coderunner;

-- Create application user if not exists
CREATE USER IF NOT EXISTS 'educode'@'%' IDENTIFIED BY 'educode_password';

-- Grant all privileges on the coderunner database to educode user
GRANT ALL PRIVILEGES ON coderunner.* TO 'educode'@'%';

-- Apply the changes
FLUSH PRIVILEGES;

-- Verify (optional, for debugging)
SELECT User, Host FROM mysql.user WHERE User = 'educode';
SHOW DATABASES;
