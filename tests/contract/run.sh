#!/bin/sh
set -eu

contract_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
harness_root=$(CDPATH= cd -- "$contract_dir/../.." && pwd)
compose_file="$contract_dir/docker-compose.yml"

if [ -z "${SPINE_SOURCE_DIR:-}" ]; then
  SPINE_SOURCE_DIR="$harness_root/../spine"
fi
if [ ! -f "$SPINE_SOURCE_DIR/Dockerfile" ] || [ ! -f "$SPINE_SOURCE_DIR/alembic.ini" ]; then
  echo "SPINE_SOURCE_DIR must point to a Spine source checkout" >&2
  exit 2
fi
SPINE_SOURCE_DIR=$(CDPATH= cd -- "$SPINE_SOURCE_DIR" && pwd)
export SPINE_SOURCE_DIR

SPINE_CONTRACT_PORT=${SPINE_CONTRACT_PORT:-18080}
case "$SPINE_CONTRACT_PORT" in
  ""|*[!0-9]*)
    echo "SPINE_CONTRACT_PORT must be an integer from 1 through 65535" >&2
    exit 2
    ;;
esac
if [ "$SPINE_CONTRACT_PORT" -lt 1 ] || [ "$SPINE_CONTRACT_PORT" -gt 65535 ]; then
  echo "SPINE_CONTRACT_PORT must be an integer from 1 through 65535" >&2
  exit 2
fi
export SPINE_CONTRACT_PORT

SPINE_TOKEN=contract-test-token
SPINE_URL="http://127.0.0.1:$SPINE_CONTRACT_PORT"
SPINE_EXPECTED_EMBEDDING_MODEL=h2-contract-embedding-1536
export SPINE_EXPECTED_EMBEDDING_MODEL SPINE_TOKEN SPINE_URL
PYTHONPATH="$harness_root/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

if [ -n "${PYTHON:-}" ]; then
  test_python() {
    "$PYTHON" -m pytest -m contract "$contract_dir"
  }
elif command -v uv >/dev/null 2>&1; then
  test_python() {
    uv run --project "$harness_root" python -m pytest -m contract "$contract_dir"
  }
elif command -v python >/dev/null 2>&1; then
  test_python() {
    python -m pytest -m contract "$contract_dir"
  }
else
  echo "Python 3.12 with the Harness dev dependencies is required" >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required for live Spine contract tests" >&2
  exit 2
}
docker compose version >/dev/null

project="harness-h2-$$"
compose() {
  docker compose --project-name "$project" --file "$compose_file" "$@"
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  compose logs --no-color || true
  compose down --rmi local --volumes --remove-orphans || true
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

compose config --quiet
compose up --build --detach --wait --wait-timeout 180
test_python
