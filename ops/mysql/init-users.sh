#!/bin/sh
set -eu

read_secret() {
    secret_path="/run/secrets/$1"
    if [ ! -r "$secret_path" ]; then
        echo "Missing database secret: $1" >&2
        exit 1
    fi
    secret_value=$(tr -d '\r\n' < "$secret_path")
    case "$secret_value" in
        *[!A-Za-z0-9_-]*|'')
            echo "Database secrets must be URL-safe random strings." >&2
            exit 1
            ;;
    esac
    if [ "${#secret_value}" -lt 32 ]; then
        echo "Database secrets must contain at least 32 characters." >&2
        exit 1
    fi
    printf '%s' "$secret_value"
}

root_password=$(read_secret mysql_root_password)
app_password=$(read_secret mysql_app_password)
migrator_password=$(read_secret mysql_migrator_password)
backup_password=$(read_secret mysql_backup_password)
schema_unreadable_password=$(
    printf 'schema-unreadable:%s' "$migrator_password" | sha256sum | awk '{print $1}'
)

deployment_database=${MYSQL_DATABASE:-clsen_data}
case "$deployment_database" in
    clsen_data|clsen_data_test_?*)
        ;;
    *)
        echo "MYSQL_DATABASE must be clsen_data or a runner-owned clsen_data_test_* database." >&2
        exit 1
        ;;
esac
case "$deployment_database" in
    *[!a-z0-9_]*)
        echo "MYSQL_DATABASE contains unsafe identifier characters." >&2
        exit 1
        ;;
esac

test_database=clsen_data_test_container
case "$deployment_database" in
    clsen_data_test_?*)
        test_database=$deployment_database
        ;;
esac

option_file=$(mktemp)
trap 'rm -f "$option_file"' EXIT
chmod 600 "$option_file"
cat > "$option_file" <<EOF
[client]
user=root
password="$root_password"
protocol=socket
EOF

mysql --defaults-extra-file="$option_file" <<SQL
CREATE DATABASE IF NOT EXISTS \`$deployment_database\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS \`$test_database\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'clsen_migrator'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$migrator_password' REQUIRE SSL;
CREATE USER IF NOT EXISTS 'clsen_app'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$app_password' REQUIRE SSL;
CREATE USER IF NOT EXISTS 'clsen_backup'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$backup_password' REQUIRE SSL;
CREATE USER IF NOT EXISTS 'clsen_schema_unreadable'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$schema_unreadable_password' REQUIRE SSL;

ALTER USER 'clsen_migrator'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$migrator_password' REQUIRE SSL;
ALTER USER 'clsen_app'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$app_password' REQUIRE SSL;
ALTER USER 'clsen_backup'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$backup_password' REQUIRE SSL;
ALTER USER 'clsen_schema_unreadable'@'%'
  IDENTIFIED WITH caching_sha2_password BY '$schema_unreadable_password' REQUIRE SSL;

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
  ON \`$deployment_database\`.* TO 'clsen_migrator'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
  ON \`$test_database\`.* TO 'clsen_migrator'@'%';

ALTER USER 'root'@'%' REQUIRE SSL;
FLUSH PRIVILEGES;
SQL
