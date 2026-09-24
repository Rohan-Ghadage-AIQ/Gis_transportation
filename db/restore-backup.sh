#!/bin/bash
set -e

# ============================================================
# Auto-restore routing_backup.backup into the PostgreSQL database
# This script runs ONCE on first container startup (when the
# data volume is empty). On subsequent startups it is skipped
# because the PostgreSQL data directory already exists.
# ============================================================

BACKUP_FILE="/backup/routing_backup.backup"
DB_NAME="${POSTGRES_DB:-routing}"

echo ""
echo "============================================================"
echo "  GIS Transportation — Database Initialization"
echo "============================================================"

# 1. Check that the backup file is mounted
if [ ! -f "$BACKUP_FILE" ]; then
    echo ""
    echo "⚠️  WARNING: Backup file not found at $BACKUP_FILE"
    echo "   The database will start EMPTY."
    echo "   To fix: place 'routing_backup.backup' in the project root"
    echo "   and restart with: docker-compose down -v && docker-compose up"
    echo ""
    exit 0
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo ""
echo "📦 Found backup file: $BACKUP_FILE ($BACKUP_SIZE)"
echo "🔄 Restoring database '$DB_NAME'..."
echo "   (This may take 5-15 minutes for large datasets)"
echo ""

# 2. Create extensions BEFORE restoring (in case they aren't in the dump)
psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$DB_NAME" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS postgis_topology;
    CREATE EXTENSION IF NOT EXISTS pgrouting;
EOSQL

echo "✅ Extensions created (PostGIS + pgRouting)"

# 3. Restore the backup
#    --no-owner:     don't try to set ownership to the original Azure user
#    --no-privileges: don't try to restore original GRANT/REVOKE
#    --role:         restore as the current postgres superuser
#    --verbose:      show progress
#    -j 2:           use 2 parallel jobs for faster restore
pg_restore \
    --username "$POSTGRES_USER" \
    --dbname "$DB_NAME" \
    --no-owner \
    --no-privileges \
    --role "$POSTGRES_USER" \
    --verbose \
    -j 2 \
    "$BACKUP_FILE" || true
# || true: pg_restore returns non-zero on warnings (e.g., "role does not exist"),
# which is expected when restoring from a different server. We don't want to fail.

echo ""
echo "============================================================"
echo "  ✅ Database restore completed!"
echo "============================================================"
echo ""

# 4. Verify key tables exist
psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$DB_NAME" <<-EOSQL
    SELECT 'road_maharashtra' AS table_name, COUNT(*) AS row_count FROM vector.road_maharashtra
    UNION ALL
    SELECT 'main_road_nodes', COUNT(*) FROM vector.main_road_nodes;
EOSQL

echo ""
echo "🚀 Database is ready for the GIS Transportation application!"
echo ""
