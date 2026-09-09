#!/bin/sh
# Bring the schema to head before serving. create_all() in the app lifespan
# builds a schema with no alembic_version row, which leaves the next migration
# with nothing to apply from — so migrations run here, not there.
set -e
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "running alembic upgrade head…"
  alembic upgrade head
fi
exec "$@"
