#!/bin/bash
set -e

echo "Starting CodeRunner application..."
echo "Waiting for database port..."

timeout=60
while ! nc -z "${MYSQL_HOST:-db}" 3306 2>/dev/null; do
    timeout=$((timeout - 1))
    if [ $timeout -le 0 ]; then
        echo "Warning: Database port not ready, continuing anyway..."
        break
    fi
    sleep 1
done

echo "Database port is open!"

# Create directories
mkdir -p /app/instance /app/logs /app/uploads /tmp/executor
chown -R appuser:appuser /app /tmp/executor 2>/dev/null || true

exec "$@"
