#!/bin/sh
# Runs once on first Postgres start. Creates the database the test suite uses.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE recallradar_test OWNER $POSTGRES_USER;
EOSQL
