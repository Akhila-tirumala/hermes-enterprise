#!/bin/bash

# Usage: ./restore.sh backup_20260627_025023.sql

BACKUP_DIR="/home/user11/hermes_enterprise/data/backups"
CONTAINER="hermes_postgres"
DB_USER="hermes"
DB_NAME="hermes_auth"
BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: ./restore.sh <backup_filename>"
    echo ""
    echo "Available backups:"
    ls -lh $BACKUP_DIR/backup_*.sql
    exit 1
fi

echo "WARNING: This will overwrite the current database!"
read -p "Are you sure? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

echo "Restoring from $BACKUP_FILE..."

cat "$BACKUP_DIR/$BACKUP_FILE" | \
  docker exec -i $CONTAINER psql -U $DB_USER $DB_NAME

if [ $? -eq 0 ]; then
    echo "✓ Database restored successfully!"
else
    echo "✗ Restore failed!"
    exit 1
fi
