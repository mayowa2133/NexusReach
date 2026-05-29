#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-nexusreach-backend-runtime}"

docker build -t "$IMAGE_NAME" -f "$ROOT_DIR/backend/Dockerfile" "$ROOT_DIR/backend"
docker run --rm "$IMAGE_NAME" python scripts/verify_runtime_dependencies.py

if [[ -n "${NEXUSREACH_API_URL:-}" ]]; then
  (cd "$ROOT_DIR/backend" && python scripts/production_smoke.py)
else
  echo "NEXUSREACH_API_URL is not set; deployed API smoke skipped."
fi
