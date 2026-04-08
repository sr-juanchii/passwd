#!/bin/sh
set -eu

ROOT_SECRET_FILE="/run/secrets/db_root_password"
APP_SECRET_FILE="/run/secrets/db_app_password"
KC_SECRET_FILE="/run/secrets/kc_db_password"

for secret_file in "$ROOT_SECRET_FILE" "$APP_SECRET_FILE" "$KC_SECRET_FILE"; do
  if [ ! -f "$secret_file" ]; then
    echo "Missing secret file: $secret_file" >&2
    exit 1
  fi
done

ROOT_PASSWORD="$(cat "$ROOT_SECRET_FILE")"
APP_PASSWORD="$(cat "$APP_SECRET_FILE")"
KC_PASSWORD="$(cat "$KC_SECRET_FILE")"

APP_PASSWORD_SQL="$(printf '%s' "$APP_PASSWORD" | sed "s/'/''/g")"
KC_PASSWORD_SQL="$(printf '%s' "$KC_PASSWORD" | sed "s/'/''/g")"

export MYSQL_PWD="$ROOT_PASSWORD"

mysql --protocol=socket --user=root <<SQL
CREATE DATABASE IF NOT EXISTS inventory_zk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS keycloak_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'app_service'@'%' IDENTIFIED BY '${APP_PASSWORD_SQL}';
CREATE USER IF NOT EXISTS 'keycloak_svc'@'%' IDENTIFIED BY '${KC_PASSWORD_SQL}';

GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_zk.* TO 'app_service'@'%';
GRANT ALL PRIVILEGES ON keycloak_db.* TO 'keycloak_svc'@'%';

ALTER USER 'app_service'@'%' REQUIRE SSL;
ALTER USER 'keycloak_svc'@'%' REQUIRE SSL;
FLUSH PRIVILEGES;
SQL

unset MYSQL_PWD
