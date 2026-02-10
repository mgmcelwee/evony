#!/usr/bin/env bash
set -euo pipefail

# run from project root no matter where we call it from
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "ERROR: $ROOT_DIR/.env not found"
  echo "Create it with:"
  echo "  cat > .env <<'EOF'"
  echo "  ADMIN_KEY=..."
  echo "  EOF"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ".env"
set +a

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
