#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".venv/bin/activate" ]; then
  # Use the project virtualenv when it exists so users can run the script directly.
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

service_names=()
service_pids=()

prefix_output() {
  local name="$1"

  awk -v prefix="[$name] " '{ print prefix $0; fflush(); }'
}

run_uvicorn() {
  if command -v uvicorn >/dev/null 2>&1; then
    exec uvicorn "$@"
  elif command -v uv >/dev/null 2>&1; then
    exec uv run uvicorn "$@"
  else
    printf "uvicorn or uv is required to start FastAPI.\n" >&2
    exit 127
  fi
}

run_celery() {
  if command -v celery >/dev/null 2>&1; then
    exec celery "$@"
  elif command -v uv >/dev/null 2>&1; then
    exec uv run celery "$@"
  else
    printf "celery or uv is required to start Celery services.\n" >&2
    exit 127
  fi
}

cleanup() {
  local status=$?
  trap - INT TERM EXIT

  if [ "${#service_pids[@]}" -gt 0 ]; then
    printf "\nStopping services...\n"
    for index in "${!service_pids[@]}"; do
      printf "Stopping %s...\n" "${service_names[$index]}"
      kill "${service_pids[$index]}" 2>/dev/null || true
    done
    wait "${service_pids[@]}" 2>/dev/null || true
  fi

  exit "$status"
}

start_service() {
  local name="$1"
  shift

  printf "[%s] starting...\n" "$name"
  "$@" > >(prefix_output "$name") 2> >(prefix_output "$name" >&2) &
  service_names+=("$name")
  service_pids+=("$!")
  printf "[%s] started with pid %s.\n" "$name" "$!"
}

trap cleanup INT TERM EXIT

if [ "${SKIP_PRESTART:-0}" != "1" ]; then
  printf "[Prestart] running database checks, migrations, and initial data setup...\n"
  bash ./scripts/prestart.sh > >(prefix_output "Prestart") 2> >(prefix_output "Prestart" >&2)
  printf "[Prestart] completed.\n"
fi

api_host="${API_HOST:-0.0.0.0}"
api_port="${API_PORT:-8083}"
celery_concurrency="${CELERY_CONCURRENCY:-1}"
flower_port="${FLOWER_PORT:-5555}"

start_service "FastAPI" \
  run_uvicorn app.main:app --reload --host "$api_host" --port "$api_port"

start_service "Celery worker" \
  run_celery -A app.core.celery_app:celery_app worker \
    --loglevel=info \
    --concurrency="$celery_concurrency" \
    --pool=prefork

start_service "Celery beat" \
  run_celery -A app.core.celery_app:celery_app beat --loglevel=info

start_service "Flower" \
  run_celery -A app.core.celery_app:celery_app flower --port="$flower_port"

printf "\nAll services started.\n"
printf "FastAPI: http://localhost:%s\n" "$api_port"
printf "Flower: http://localhost:%s\n" "$flower_port"
printf "Press Ctrl+C to stop all services.\n"

while true; do
  running_pids="$(jobs -pr)"

  for index in "${!service_pids[@]}"; do
    pid="${service_pids[$index]}"
    case " $running_pids " in
      *" $pid "*)
        ;;
      *)
        if wait "$pid"; then
          status=0
        else
          status=$?
        fi
        printf "%s exited with status %s.\n" "${service_names[$index]}" "$status"
        exit "$status"
        ;;
    esac
  done

  sleep 1
done
