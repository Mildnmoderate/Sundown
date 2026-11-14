#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
export AGENT_CMD=".venv/bin/python -m agent.worker"

pkill -f "uvicorn systems.main:app" 2>/dev/null
pkill -f "agent.worker" 2>/dev/null
rm -f .agent.pid
sleep 1

python - <<'EOF' || python -m scripts.seed_experiences
import sys
from common.db import db
sys.exit(0 if db()["experiences"].count_documents({"embedding": {"$exists": True}}) >= 6 else 1)
EOF

python -m uvicorn systems.main:app --port 8001 &
until curl -sf localhost:8001/health >/dev/null; do sleep 1; done
curl -s -X POST localhost:8001/control/start_agent >/dev/null
echo; echo "READY: open http://localhost:8001   (Ctrl+C stops everything)"
trap 'pkill -f "agent.worker"; kill 0' INT TERM
wait