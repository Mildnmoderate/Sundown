# Sundown

**An offboarding agent that doesn't stop until the ex-employee's access is actually dead.**

Built for the MongoDB Agents in Context hackathon (Toronto), track **Finish the Job**.
Everything in this repository was written during the event.

## The problem

When someone leaves, "revoke access" spans five systems that don't hold still. A 200 OK
from an API is a *claim*, not proof: tokens can keep working after a "successful" revoke,
revocation can take effect minutes later, and APIs change underneath you. Most agents
report success the moment the request is sent. Sundown reports success only when an
independent probe proves the access is gone.

## How it answers the track's three questions

| Question | Sundown's answer |
|---|---|
| Took effect vs. only sent? | Every step moves `planned -> sending -> sent -> verified`. `sent` means the call returned 2xx. `verified` requires a separate probe (the employee's own token is rejected) and the evidence is stored with the step. |
| Resume after a crash without replaying history? | Task state and step state live in Atlas. A restarted worker loads only the steps that are not `verified`, and probes a half-finished step before resending it. |
| Adapt when a system changes? | On failure the agent reads the system's schema, searches Atlas Vector Search for similar past adaptations, adapts the call, re-verifies, and stores the new experience. |

## Architecture

```
  ui/index.html  <---- SSE /stream (Atlas change stream on `events`) ----+
       |                                                                  |
       v                                                                  |
  systems/main.py  (FakeCorp: 5 mock systems + control plane)             |
       |  /control/start inserts a pending task                           |
       v                                                                  |
  MongoDB Atlas:  tasks | events | adapters | experiences (Vector Search) -+
       ^
       |  agent worker claims tasks, writes events, probes systems
  agent worker
```

- **FakeCorp (`systems/main.py`)**: Okta, GitHub, Slack, Google Workspace and Expenses mocks.
  Each has an in-memory token store, `remove_user`, a `/me` probe endpoint, `/config` and `/reset`.
- **Chaos modes** (toggle live from the UI):
  - **GitHub lies**: `remove_user` returns 200 but the token keeps working. A second call,
    `POST /github/revoke_sessions`, really kills it.
  - **Google delay**: the token only dies `delay_seconds` (about 20) after the call.
  - **Okta v2 drift**: field `status` becomes `state`, the old deactivate endpoint returns 400,
    and `PUT /okta/users/{id}/state` is the new path.
- **UI (`ui/index.html`)**: step table (grey planned, yellow sent, green verified, red failed),
  a "ground truth" column that shows whether the token actually still works, chaos toggles,
  a Kill/Restart agent button for the crash demo, and a proof drawer with the stored evidence.
- **Atlas**: `tasks`, `events`, `adapters`, `experiences` plus a Vector Search index on
  `experiences`. The `events` change stream drives the live UI.

## Agent contract (what the worker reads and writes)

- **Claim work**: documents in `tasks` with `status: "pending"`:
  `{employee, systems, authorizedBy, createdAt}`.
- **Report progress**: insert into `events`:
  `{taskId, system, state, detail, evidence, ts}` where `state` is one of
  `planned | sending | sent | verified | failed | adapted`.
- **Probe credentials**: `GET /control/credentials/{user}` (tokens are `tok-<system>-<user>`).
- **Crash demo**: the worker writes its PID to `.agent.pid`; the UI's Kill button hard-kills it.
  Set `AGENT_CMD` (for example `python -m sundown.agent`) so Restart can relaunch it.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env                                 # fill in MONGODB_URI, LLM_*, EMBED_*
python -m scripts.setup_db                           # collections + Vector Search index (once)
python -m scripts.check_all                          # health check: Atlas, LLM, embeddings, index, change streams

# Terminal 1: mock systems + UI at http://localhost:8001
python -m uvicorn systems.main:app --port 8001

# Terminal 2: the agent worker (see agent docs)
```

## Demo

See [DEMO.md](DEMO.md) for the 3-minute live script and the 1-minute video shot list.

## Stack

Python, FastAPI, MongoDB Atlas (collections, change streams, Vector Search), Groq-hosted LLM,
sentence-transformers embeddings. No Streamlit.
