CREATE DATABASE IF NOT EXISTS inventory_zk
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE inventory_zk;

CREATE TABLE IF NOT EXISTS servers (
    id CHAR(36) NOT NULL,
    hostname VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    operating_system VARCHAR(100) NOT NULL,
    owner_user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_owner (owner_user_id),
    INDEX idx_hostname (hostname)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS credentials (
    id CHAR(36) NOT NULL,
    server_id CHAR(36) NOT NULL,
    owner_user_id CHAR(36) NOT NULL,
    credential_username VARCHAR(255) NOT NULL,
    cipher_text VARBINARY(4096) NOT NULL,
    wrapped_dek VARBINARY(512) NOT NULL,
    iv VARBINARY(16) NOT NULL,
    auth_tag VARBINARY(32) NOT NULL,
    pbkdf2_salt VARBINARY(32) NOT NULL,
    pbkdf2_iterations INT UNSIGNED NOT NULL DEFAULT 600000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_cred_owner (owner_user_id),
    INDEX idx_cred_server (server_id),
    CONSTRAINT fk_credentials_server
      FOREIGN KEY (server_id) REFERENCES servers (id)
      ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
