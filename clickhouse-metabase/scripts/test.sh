#!/usr/bin/env bash
# Own a fresh project; never delete the normal development stack's volumes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
command -v docker >/dev/null || { echo 'Docker with Compose v2 is required.' >&2; exit 1; }
docker compose version >/dev/null

export COMPOSE_PROJECT_NAME="cookbook-metabase-test-$("$PYTHON" -c 'import uuid; print(uuid.uuid4().hex)')"
export CLICKHOUSE_USER=cookbook CLICKHOUSE_PASSWORD=local-clickhouse-only
export METABASE_DB_PASSWORD=local-metabase-db-only
export CLICKHOUSE_HTTP_PORT=0 METABASE_PORT=0
compose=(docker compose --file compose.yaml --project-name "$COMPOSE_PROJECT_NAME")
mkdir -p artifacts
printf '%s\n' "$COMPOSE_PROJECT_NAME" > artifacts/project.txt
: > artifacts/smoke.log

cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" ps -a > artifacts/services.txt 2>&1 || true
  "${compose[@]}" logs --no-color > artifacts/compose.log 2>&1 || true
  if ! "${compose[@]}" down --volumes --remove-orphans --timeout 30; then
    echo "Cleanup failed for disposable project $COMPOSE_PROJECT_NAME" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"${compose[@]}" config --quiet
"${compose[@]}" up -d --wait --wait-timeout 600
"$PYTHON" scripts/smoke.py | tee artifacts/smoke.log
