#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".venv/bin/activate" ]; then
  # Allow this script to run directly without requiring manual venv activation.
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

run_python() {
  if command -v python >/dev/null 2>&1; then
    python "$@"
  elif command -v uv >/dev/null 2>&1; then
    uv run python "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 "$@"
  else
    printf "python, python3, or uv is required to run prestart.\n" >&2
    exit 127
  fi
}

run_alembic() {
  if command -v alembic >/dev/null 2>&1; then
    alembic "$@"
  elif command -v uv >/dev/null 2>&1; then
    uv run alembic "$@"
  else
    printf "alembic or uv is required to run database migrations.\n" >&2
    exit 127
  fi
}

set -x

# Let the DB start
run_python -m app.backend_pre_start

# Run migrations
run_alembic upgrade head

# Create initial data in DB
run_python -m app.initial_data
