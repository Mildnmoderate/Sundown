#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
curl -sf localhost:8001/health >/dev/null || { echo "Server not running. In another terminal run: ./run.sh"; exit 1; }
python -m scripts.check_all && python -m scripts.test_all "$@"