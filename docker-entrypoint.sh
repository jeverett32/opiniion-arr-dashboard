#!/bin/sh
set -e
mkdir -p /app/data
if [ ! -f /app/data/arr.db ] && [ -f /app/data-seed/arr.db ]; then
  echo "Seeding arr.db from image..."
  cp /app/data-seed/arr.db /app/data/arr.db
fi
exec "$@"
