#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=business_password="$AGENT_DB_PASSWORD" \
  --set=checkpoint_password="$CHECKPOINT_DB_PASSWORD" \
  --file=/opt/brandflow/postgres-roles.sql
