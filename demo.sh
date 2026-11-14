#!/usr/bin/env bash
H='content-type: application/json'
curl -s -X POST localhost:8001/control/reset -H "$H" -d '{"clear_db":true}' >/dev/null
curl -s -X POST localhost:8001/control/chaos -H "$H" -d '{"on":true}' >/dev/null
sleep 3
curl -s -X POST localhost:8001/control/start_agent >/dev/null
curl -s localhost:8001/control/state | python3 -c "import sys,json; a=json.load(sys.stdin)['agent']; print('agent running:', a['running'], '| chaos: ON | slate: clean')"