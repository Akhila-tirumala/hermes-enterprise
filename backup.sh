#!/bin/bash

# ── Config ────────────────────────────────────────────────────────────────────
BACKUP_DIR="/home/user11/hermes_enterprise/data/backups"
CONTAINER="hermes_postgres"
DB_USER="hermes"
DB_NAME="hermes_auth"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7
LOG_FILE="$BACKUP_DIR/backup.log"

# ── Run backup ────────────────────────────────────────────────────────────────
echo "[$DATE] Starting backup..." >> $LOG_FILE

docker exec $CONTAINER pg_dump -U $DB_USER $DB_NAME \
  > "$BACKUP_DIR/backup_$DATE.sql"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$BACKUP_DIR/backup_$DATE.sql" | cut -f1)
    echo "[$DATE] Backup successful — $SIZE" >> $LOG_FILE
else
    echo "[$DATE] ERROR — backup failed!" >> $LOG_FILE
    exit 1
fi

# ── Delete backups older than 7 days ─────────────────────────────────────────
find $BACKUP_DIR -name "backup_*.sql" -mtime +$KEEP_DAYS -delete
echo "[$DATE] Old backups cleaned up" >> $LOG_FILE

# ── List current backups ──────────────────────────────────────────────────────
echo "[$DATE] Current backups:" >> $LOG_FILE
ls -lh $BACKUP_DIR/backup_*.sql 2>/dev/null >> $LOG_FILE
echo "─────────────────────────────────" >> $LOG_FILE
