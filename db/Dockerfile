# PostgreSQL 17 + PostGIS 3.5 + pgRouting
# This image auto-restores the routing_backup.backup on first startup.

FROM postgis/postgis:17-3.5

# Install pgRouting from official Debian/Ubuntu repos
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-17-pgrouting \
    && rm -rf /var/lib/apt/lists/*

# Copy the initialization script that restores the backup
COPY restore-backup.sh /docker-entrypoint-initdb.d/10-restore-backup.sh
RUN chmod +x /docker-entrypoint-initdb.d/10-restore-backup.sh

# The backup file is mounted at runtime via docker-compose volume,
# NOT baked into the image (keeps image small).
# Expected mount: ./routing_backup.backup -> /backup/routing_backup.backup

EXPOSE 5432
