"""FakeCorp: five mock systems with in-memory token stores, plus demo control
endpoints and an SSE stream of the Atlas `events` change stream.

Run from the repo root:
    python -m uvicorn systems.main:app --port 8001

Contract with the agent (see README.md):
  * Probe credentials are deterministic: token = "tok-<system>-<user>"
    (or GET /control/credentials/<user>).
  * The agent reports progress by INSERTING docs into Atlas `events`:
      {taskId, system, state, detail, evidence, ts}
    state is one of planned | sending | sent | verified | failed | adapted.
  * "Start" inserts a pending doc into `tasks`; the agent worker claims it.
  * The agent writes its PID into .agent.pid so the Kill button can crash it.
"""
import asyncio
import copy
import json
import os
import shlex
import signal
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from common.db import db

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / ".agent.pid"
UI_FILE = ROOT / "ui" / "index.html"

SYSTEMS = ["okta", "github", "slack", "google", "expenses"]
USERS = ["priya", "marcus"]          # priya is leaving; marcus is the bystander for the scope gate

DEFAULT_CONFIG = {
    "okta": {"version": "v1"},
    "github": {"lies_on_revoke": False},
    "slack": {},
    "google": {"delay_seconds": 0},
    "expenses": {},
}
CHAOS_ON = {
    "okta": {"version": "v2"},
    "github": {"lies_on_revoke": True},
    "google": {"delay_seconds": 20},
}

# ----------------------------------------------------------------------------
# In-memory state
# ----------------------------------------------------------------------------
STATE: dict[str, dict] = {}


def token_for(system: str, user: str) -> str:
    return f"tok-{system}-{user}"


def reset_system(name: str) -> None:
    STATE[name] = {
        "config": copy.deepcopy(DEFAULT_CONFIG[name]),
        "tokens": {token_for(name, u): {"user": u, "dead_at": None} for u in USERS},
    }


for _s in SYSTEMS:
    reset_system(_s)


def alive(name: str, tok: str) -> bool:
    t = STATE[name]["tokens"].get(tok)
    if not t:
        return False
    return t["dead_at"] is None or time.time() < t["dead_at"]


def user_active(name: str, user: str) -> bool:
    return any(alive(name, tok) for tok, t in STATE[name]["tokens"].items() if t["user"] == user)


def kill_tokens(name: str, user: str, delay: float = 0.0) -> None:
    when = time.time() + delay
    for t in STATE[name]["tokens"].values():
        if t["user"] == user and t["dead_at"] is None:
            t["dead_at"] = when


def bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_user(user: str) -> None:
    if user not in USERS:
        raise HTTPException(404, {"error": "unknown_user", "user": user})


def apply_config(name: str, updates: dict) -> dict:
    if name not in STATE:
        raise HTTPException(404, f"unknown system {name}")
    cfg = STATE[name]["config"]
    for k, v in updates.items():
        if k not in cfg:
            raise HTTPException(400, f"unknown key '{k}' for {name}; allowed: {list(cfg)}")
        if k == "version" and v not in ("v1", "v2"):
            raise HTTPException(400, "version must be 'v1' or 'v2'")
        if k == "delay_seconds":
            try:
                v = max(0.0, float(v))
            except (TypeError, ValueError):
                raise HTTPException(400, "delay_seconds must be a number")
        if k == "lies_on_revoke":
            v = bool(v)
        cfg[k] = v
    return cfg


def ser(doc: Any) -> Any:
    return json.loads(json.dumps(doc, default=str))


# ----------------------------------------------------------------------------
# remove_user behaviour per system (this is where the chaos lives)
# ----------------------------------------------------------------------------
def do_remove(name: str, user: str) -> dict:
    cfg = STATE[name]["config"]

    if name == "okta" and cfg["version"] == "v2":
        raise HTTPException(400, {
            "error": "endpoint_removed",
            "detail": "POST /okta/remove_user was removed in API v2. "
                      "Use PUT /okta/users/{user_id}/state with {\"state\": \"deprovisioned\"}.",
        })

    if name == "github" and cfg["lies_on_revoke"]:
        # THE LIE: 200 OK, nothing changes, the token keeps working.
        return {"ok": True, "system": name, "user": user}

    delay = float(cfg["delay_seconds"]) if name == "google" else 0.0
    kill_tokens(name, user, delay)
    return {"ok": True, "system": name, "user": user}


class UserBody(BaseModel):
    user_id: str


def make_router(name: str) -> APIRouter:
    r = APIRouter(prefix=f"/{name}", tags=[name])

    @r.get("/me")
    def me(authorization: str | None = Header(None)):
        """The probe: does this token still work?"""
        tok = bearer(authorization)
        if tok is None or not alive(name, tok):
            raise HTTPException(401, {"error": "invalid_token", "system": name})
        return {"system": name, "user": STATE[name]["tokens"][tok]["user"], "token_valid": True}

    @r.post("/remove_user")
    def remove_user(body: UserBody):
        require_user(body.user_id)
        return do_remove(name, body.user_id)

    @r.get("/config")
    def get_config():
        return STATE[name]["config"]

    @r.post("/config")
    def set_config(body: dict):
        return apply_config(name, body)

    @r.post("/reset")
    def reset():
        reset_system(name)
        return {"ok": True, "system": name}

    if name == "github":
        @r.post("/revoke_sessions")
        def revoke_sessions(body: UserBody):
            """The second call that really kills the token, so a retry can succeed."""
            require_user(body.user_id)
            kill_tokens(name, body.user_id)
            return {"ok": True, "system": name, "user": body.user_id, "revoked": True}

    if name == "okta":
        @r.put("/users/{user_id}/state")
        def set_state(user_id: str, body: dict):
            """New deactivate path, only exists in API v2."""
            require_user(user_id)
            if STATE[name]["config"]["version"] != "v2":
                raise HTTPException(404, "no such endpoint in API v1")
            if body.get("state") != "deprovisioned":
                raise HTTPException(400, "state must be 'deprovisioned'")
            kill_tokens(name, user_id)
            return {"ok": True, "system": name, "user": user_id, "state": "deprovisioned"}

        @r.get("/users/{user_id}")
        def get_user(user_id: str):
            """v1 returns `status`; v2 renames it to `state`."""
            require_user(user_id)
            active = user_active(name, user_id)
            if STATE[name]["config"]["version"] == "v2":
                return {"id": user_id, "state": "active" if active else "deprovisioned"}
            return {"id": user_id, "status": "ACTIVE" if active else "DEPROVISIONED"}

        @r.get("/schema")
        def schema():
            if STATE[name]["config"]["version"] == "v2":
                return {"version": "v2", "status_field": "state",
                        "deactivate": {"method": "PUT", "path": "/okta/users/{id}/state",
                                       "body": {"state": "deprovisioned"}}}
            return {"version": "v1", "status_field": "status",
                    "deactivate": {"method": "POST", "path": "/okta/remove_user",
                                   "body": {"user_id": "{id}"}}}

    return r


# ----------------------------------------------------------------------------
# Agent process helpers (kill / restart for the crash demo)
# ----------------------------------------------------------------------------
def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        # NOTE: os.kill(pid, 0) would TERMINATE the process on Windows, so ask tasklist.
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        close = stat.rfind(")")
        if close >= 0 and stat[close + 2:close + 3] == "Z":
            return False
    except OSError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def hard_kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


# ----------------------------------------------------------------------------
# Control plane
# ----------------------------------------------------------------------------
control = APIRouter(prefix="/control", tags=["control"])


class ToggleBody(BaseModel):
    system: str
    key: str
    value: Any


class ChaosBody(BaseModel):
    on: bool


class ResetBody(BaseModel):
    clear_db: bool = True


class StartBody(BaseModel):
    employee: str = "priya"
    authorized_by: str = "hr:dana"
    systems: list[str] | None = None


@control.get("/state")
def control_state():
    pid = read_pid()
    out: dict[str, Any] = {
        name: {"config": STATE[name]["config"],
               "users": {u: user_active(name, u) for u in USERS}}
        for name in SYSTEMS
    }
    out["agent"] = {"pid": pid, "running": pid_running(pid),
                    "can_restart": bool(os.environ.get("AGENT_CMD"))}
    return out


@control.get("/credentials/{user}")
def credentials(user: str):
    require_user(user)
    return {name: token_for(name, user) for name in SYSTEMS}


@control.post("/toggle")
def toggle(body: ToggleBody):
    return apply_config(body.system, {body.key: body.value})


@control.post("/chaos")
def chaos(body: ChaosBody):
    for name in SYSTEMS:
        cfg = CHAOS_ON.get(name) if body.on else DEFAULT_CONFIG[name]
        if cfg:
            apply_config(name, cfg)
    return {"ok": True, "on": body.on}


@control.post("/reset")
def reset_all(body: ResetBody | None = None):
    clear_db = True if body is None else body.clear_db
    for name in SYSTEMS:
        reset_system(name)
    result: dict[str, Any] = {"ok": True, "db_cleared": False}
    if clear_db:
        try:
            db()["events"].delete_many({})
            db()["tasks"].delete_many({})
            result["db_cleared"] = True
        except Exception as e:  # keep the in-memory reset even if Atlas is unreachable
            result["db_error"] = str(e)[:200]
    return result


@control.post("/start")
def start(body: StartBody):
    require_user(body.employee)
    systems = body.systems or SYSTEMS
    bad = [s for s in systems if s not in SYSTEMS]
    if bad:
        raise HTTPException(400, f"unknown systems: {bad}")
    doc = {
        "status": "pending",
        "employee": body.employee,
        "systems": systems,
        "authorizedBy": body.authorized_by,
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        res = db()["tasks"].insert_one(doc)
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {str(e)[:200]}")
    return {"taskId": str(res.inserted_id), "employee": body.employee, "systems": systems}


@control.post("/kill_agent")
def kill_agent():
    pid = read_pid()
    if not pid_running(pid):
        raise HTTPException(409, "agent is not running (no live PID in .agent.pid)")
    hard_kill(pid)
    return {"ok": True, "killed_pid": pid}


@control.post("/start_agent")
def start_agent():
    cmd = os.environ.get("AGENT_CMD")
    if not cmd:
        raise HTTPException(400, "set AGENT_CMD (e.g. 'python -m sundown.agent') before starting uvicorn")
    if pid_running(read_pid()):
        raise HTTPException(409, "agent already running")
    proc = subprocess.Popen(shlex.split(cmd, posix=(os.name != "nt")), cwd=str(ROOT))
    PID_FILE.write_text(str(proc.pid))
    return {"ok": True, "pid": proc.pid}


# ----------------------------------------------------------------------------
# Events: history + live SSE from the Atlas change stream
# ----------------------------------------------------------------------------
SUBS: set[asyncio.Queue] = set()
LOOP: asyncio.AbstractEventLoop | None = None


def _broadcast(doc: dict) -> None:
    payload = json.dumps(doc, default=str)
    for q in list(SUBS):
        q.put_nowait(payload)


def _watch_events() -> None:
    while True:
        try:
            with db()["events"].watch([{"$match": {"operationType": "insert"}}]) as stream:
                print("[stream] watching Atlas events change stream")
                for change in stream:
                    if LOOP is not None:
                        LOOP.call_soon_threadsafe(_broadcast, change["fullDocument"])
        except Exception as e:
            print(f"[stream] change stream error: {e!r}; retrying in 3s")
            time.sleep(3)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global LOOP
    LOOP = asyncio.get_running_loop()
    threading.Thread(target=_watch_events, daemon=True).start()
    yield


app = FastAPI(title="FakeCorp", lifespan=lifespan)
for _name in SYSTEMS:
    app.include_router(make_router(_name))
app.include_router(control)


def _task_filter(task_id: str) -> dict:
    ors: list[dict] = [{"taskId": task_id}]
    try:
        ors.append({"taskId": ObjectId(task_id)})
    except Exception:
        pass
    return {"$or": ors}


@app.get("/events")
def list_events(task_id: str | None = None, limit: int = 300):
    try:
        q = _task_filter(task_id) if task_id else {}
        docs = list(db()["events"].find(q).sort([("ts", -1), ("_id", -1)]).limit(limit))
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {str(e)[:200]}")
    docs.reverse()
    return [ser(d) for d in docs]


@app.get("/stream")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    SUBS.add(q)

    async def gen():
        try:
            yield {"event": "hello", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": "event", "data": payload}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            SUBS.discard(q)

    return EventSourceResponse(gen())


@app.get("/health")
def health():
    return {"ok": True, "systems": SYSTEMS}


@app.get("/")
def index():
    return FileResponse(UI_FILE)
