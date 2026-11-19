#!/bin/sh
set -eu
if [ "${1:-}" = '--healthcheck' ]; then
    PRODUCTION_SERVICE_TOKEN=$(cat /run/secrets/production_service_token)
    export PRODUCTION_SERVICE_TOKEN
    exec java -jar /app/production.jar --healthcheck
fi
case "${PRODUCTION_DATABASE_NAME:-}" in
    clsen_production|clsen_production_test_*) ;;
    *) echo 'Invalid production database name' >&2; exit 1 ;;
esac
case "$PRODUCTION_DATABASE_NAME" in *[!a-z0-9_]*) exit 1 ;; esac
keytool -importcert -noprompt -alias mysql-ca -file /run/secrets/mysql_ca_certificate \
    -keystore /tmp/mysql-ca.p12 -storetype PKCS12 -storepass changeit >/dev/null 2>&1
export PRODUCTION_DATABASE_URL="jdbc:mysql://mysql:3306/$PRODUCTION_DATABASE_NAME?sslMode=VERIFY_IDENTITY&trustCertificateKeyStoreUrl=file:/tmp/mysql-ca.p12&trustCertificateKeyStoreType=PKCS12&trustCertificateKeyStorePassword=changeit&connectionTimeZone=UTC"
if [ "${1:-}" = '--migrate' ]; then
    export PRODUCTION_MIGRATION_USER=clsen_production_migrator
    PRODUCTION_MIGRATION_PASSWORD=$(cat /run/secrets/production_migrator_password)
    export PRODUCTION_MIGRATION_PASSWORD
else
    export SERVER_ADDRESS=0.0.0.0
    export PRODUCTION_DATABASE_USER=clsen_production_app
    PRODUCTION_DATABASE_PASSWORD=$(cat /run/secrets/production_app_password)
    PRODUCTION_SERVICE_TOKEN=$(cat /run/secrets/production_service_token)
    export PRODUCTION_DATABASE_PASSWORD PRODUCTION_SERVICE_TOKEN
fi
if [ "$#" -eq 0 ]; then set -- --serve; fi
exec java -jar /app/production.jar "$@"
