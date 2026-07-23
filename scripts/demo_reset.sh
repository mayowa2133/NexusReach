#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=demo_env.sh
source "$ROOT_DIR/scripts/demo_env.sh"

SCENARIO="${1:-returning}"
if [[ "$SCENARIO" != "returning" && "$SCENARIO" != "onboarding" ]]; then
  echo "Usage: $0 [returning|onboarding]" >&2
  exit 2
fi

DEFAULT_PYTHON="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$DEFAULT_PYTHON" ]]; then DEFAULT_PYTHON=python3; fi
PYTHON_BIN="${NEXUSREACH_PYTHON:-$DEFAULT_PYTHON}"
cd "$ROOT_DIR/backend"
PYTHONPATH=. "$PYTHON_BIN" scripts/e2e_prepare_db.py
PYTHONPATH=. "$PYTHON_BIN" -m alembic upgrade head
PYTHONPATH=. "$PYTHON_BIN" scripts/demo_reset.py --scenario "$SCENARIO"
