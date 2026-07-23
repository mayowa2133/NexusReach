#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=demo_env.sh
source "$ROOT_DIR/scripts/demo_env.sh"

SCENARIO=returning
RESET=true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario)
      SCENARIO="${2:-}"
      shift 2
      ;;
    --no-reset)
      RESET=false
      shift
      ;;
    *)
      echo "Usage: $0 [--scenario returning|onboarding] [--no-reset]" >&2
      exit 2
      ;;
  esac
done
if [[ "$SCENARIO" != "returning" && "$SCENARIO" != "onboarding" ]]; then
  echo "Scenario must be returning or onboarding." >&2
  exit 2
fi

DEFAULT_PYTHON="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$DEFAULT_PYTHON" ]]; then DEFAULT_PYTHON=python3; fi
PYTHON_BIN="${NEXUSREACH_PYTHON:-$DEFAULT_PYTHON}"
for command in "$PYTHON_BIN" npm curl redis-server redis-cli; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

REDIS_PID=""
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  for pid in "$FRONTEND_PID" "$BACKEND_PID" "$REDIS_PID"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT INT TERM

if ! redis-cli -h 127.0.0.1 -p 6381 ping >/dev/null 2>&1; then
  redis-server --bind 127.0.0.1 --port 6381 --save '' --appendonly no --protected-mode yes >/tmp/nexusreach-demo-redis.log 2>&1 &
  REDIS_PID=$!
  for _ in {1..30}; do
    redis-cli -h 127.0.0.1 -p 6381 ping >/dev/null 2>&1 && break
    sleep 0.1
  done
fi
if ! redis-cli -h 127.0.0.1 -p 6381 ping >/dev/null 2>&1; then
  echo "Demo Redis did not start; see /tmp/nexusreach-demo-redis.log" >&2
  exit 1
fi

if [[ "$RESET" == true ]]; then
  "$ROOT_DIR/scripts/demo_reset.sh" "$SCENARIO"
fi

(
  cd "$ROOT_DIR/backend"
  PYTHONPATH=. "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  npm run dev:bypass -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

for _ in {1..120}; do
  if curl --fail --silent http://127.0.0.1:8000/api/health >/dev/null && \
     curl --fail --silent http://127.0.0.1:5173 >/dev/null; then
    echo
    echo "NexusReach safe demo is ready"
    echo "  App:      http://127.0.0.1:5173"
    echo "  API:      http://127.0.0.1:8000"
    echo "  Scenario: $SCENARIO"
    echo "  Reset:    ./scripts/demo_reset.sh $SCENARIO"
    echo "  Stop:     Ctrl-C"
    echo
    wait "$BACKEND_PID" "$FRONTEND_PID"
    exit $?
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "A demo process exited before becoming ready." >&2
    exit 1
  fi
  sleep 0.25
done

echo "Timed out waiting for the NexusReach demo." >&2
exit 1
