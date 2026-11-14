"""Sundown agent worker. Code owns the loop; only a successful probe can mark a step verified.
Groq (via drift.py and narrate.py) only explains and summarizes. It never decides."""
import atexit, os, threading, time, uuid, datetime as dt
from pathlib import Path
import httpx
from pymongo import ReturnDocument
from common.db import db
from agent import drift, narrate

BASE = os.environ.get("SYSTEMS_URL", "http://localhost:8001")
ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / ".agent.pid"
LEASE = 6                                            # seconds
PAUSE = float(os.environ.get("AGENT_PAUSE", "1.5"))  # demo pacing; set 0 to disable
SYSTEMS = ["okta", "github", "slack", "google", "expenses"]

# systems known to propagate slowly: keep probing, do not resend
WINDOWS = {"google": 30}

ESCALATE = {"github": {"method": "POST", "path": "/github/revoke_sessions",
                       "body": {"user_id": "{user}"}}}


def now():
    return dt.datetime.now(dt.timezone.utc)


def default_action(system):
    return {"method": "POST", "path": f"/{system}/remove_user", "body": {"user_id": "{user}"}}


def fill(obj, user):
    if isinstance(obj, str):
        return obj.replace("{user}", user)
    if isinstance(obj, dict):
        return {k: fill(v, user) for k, v in obj.items()}
    return obj


def emit(tid, system, state, detail, evidence=None):
    db()["events"].insert_one({"taskId": str(tid), "system": system, "state": state,
                               "detail": detail, "evidence": evidence, "ts": now()})
    print(f"[{system}] {state}: {detail}")


def set_step(tid, system, **f):
    db()["tasks"].update_one({"_id": tid}, {"$set": {f"steps.{system}.{k}": v for k, v in f.items()}})


def probe(system, token):
    """Ground truth. Only HTTP 401 counts as 'dead'. A network error proves nothing."""
    try:
        r = httpx.get(f"{BASE}/{system}/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return {"request": f"GET /{system}/me", "status": r.status_code,
                "passed": r.status_code == 401, "at": now()}
    except Exception as e:
        return {"request": f"GET /{system}/me", "status": None, "passed": False,
                "error": str(e)[:100], "at": now()}


def wait_dead(tid, system, token, window):
    start, n, ev = time.time(), 0, None
    while True:
        n += 1
        ev = probe(system, token)
        if ev["passed"]:
            return ev
        if time.time() - start >= window:
            return ev
        emit(tid, system, "sent", f"probe #{n}: token still works (HTTP {ev['status']}), waiting...", ev)
        time.sleep(2)


def call(action, user, key):
    return httpx.request(action["method"], BASE + fill(action["path"], user),
                         json=fill(action.get("body"), user),
                         headers={"Idempotency-Key": key}, timeout=15)


def current_action(system):
    a = db()["adapters"].find_one({"system": system})
    return a["action"] if a else default_action(system)


def run_step(task, system, token):
    tid, user = task["_id"], task["employee"]
    key = f"{tid}:{system}:revoke"
    step = db()["tasks"].find_one({"_id": tid})["steps"][system]

    if step["state"] == "verified":
        emit(tid, system, "verified", "resumed: already verified before the crash, skipped")
        return True

    if step["state"] in ("sending", "sent"):         # crash recovery: probe BEFORE re-sending
        ev = probe(system, token)
        emit(tid, system, "sent", "recovery probe after restart: " +
             ("token already dead" if ev["passed"] else "token still works, will retry"), ev)
        if ev["passed"]:
            set_step(tid, system, state="verified", verifiedAt=now(), evidence=ev)
            emit(tid, system, "verified", "verified by probe after recovery (no duplicate call sent)", ev)
            return True

    drifted = False
    attempt = 0
    while attempt < 4:
        attempt += 1
        action = ESCALATE[system] if (attempt > 1 and system in ESCALATE) else current_action(system)
        set_step(tid, system, state="sending", attempts=attempt, idempotencyKey=key)   # write-ahead
        emit(tid, system, "sending", f"attempt {attempt}: {action['method']} {fill(action['path'], user)}")
        try:
            r = call(action, user, key)
        except Exception as e:
            emit(tid, system, "sending", f"network error, retrying: {str(e)[:80]}")
            time.sleep(2)
            continue

        if r.status_code >= 400:
            emit(tid, system, "failed", f"HTTP {r.status_code}: {r.text[:200]}", {"status": r.status_code})
            if drifted:
                break
            drifted = True
            attempt -= 1                              # an adaptation is not a retry
            res = drift.resolve(system, r.status_code, r.text, user)
            if not res["ok"]:
                emit(tid, system, "failed", "no usable past fix found", res)
                break
            emit(tid, system, "adapted",
                 res["note"] + (f" | LLM check: {res['llm_note']}" if res.get("llm_note") else ""), res)
            continue

        set_step(tid, system, state="sent", sentAt=now())
        emit(tid, system, "sent", f"HTTP {r.status_code} is only a claim. Probing with {user}'s own token")
        ev = wait_dead(tid, system, token,
                       window=WINDOWS.get(system, 8) if attempt == 1 else 35)
        if ev["passed"]:
            set_step(tid, system, state="verified", verifiedAt=now(), evidence=ev)
            emit(tid, system, "verified", f"token rejected (HTTP {ev['status']}): access is dead", ev)
            return True
        emit(tid, system, "sent", "API said OK but the token STILL works. Not verified, retrying", ev)

    set_step(tid, system, state="failed")
    emit(tid, system, "failed", "gave up: access not proven dead")
    return False


def claim(owner):
    t = now()
    return db()["tasks"].find_one_and_update(
        {"$or": [{"status": "pending"},
                 {"status": "running", "leaseExpiresAt": {"$lt": t}}]},
        {"$set": {"status": "running", "leaseOwner": owner,
                  "leaseExpiresAt": t + dt.timedelta(seconds=LEASE)}},
        sort=[("createdAt", 1)], return_document=ReturnDocument.AFTER)


def heartbeat(tid, owner, stop):
    while not stop.is_set():
        r = db()["tasks"].update_one({"_id": tid, "leaseOwner": owner},
                                     {"$set": {"leaseExpiresAt": now() + dt.timedelta(seconds=LEASE)}})
        if r.matched_count == 0:
            os._exit(1)                               # lost the lease: stop, never double-act
        time.sleep(2)


def warm_up():
    try:
        from common.embed import embed
        embed("warm up")
    except Exception as e:
        print(f"[warmup] skipped: {e!r}")


def process_task(owner, task):
    tid, user = task["_id"], task["employee"]

    if "steps" not in task:                           # new task (not a resume)
        db()["adapters"].delete_many({})
        systems = task.get("systems") or SYSTEMS
        steps = {s: {"state": "planned", "attempts": 0, "idempotencyKey": f"{tid}:{s}:revoke",
                     "sentAt": None, "verifiedAt": None, "evidence": None} for s in systems}
        db()["tasks"].update_one({"_id": tid}, {"$set": {"steps": steps}})
        for s in systems:
            emit(tid, s, "planned", f"revoke {user} (authorized by {task.get('authorizedBy')})")
        task["steps"] = steps
    else:
        emit(tid, "task", "planned", f"resumed by {owner}: skipping verified steps")

    stop = threading.Event()
    heartbeat_thread = threading.Thread(target=heartbeat, args=(tid, owner, stop), daemon=True)
    heartbeat_thread.start()
    creds = httpx.get(f"{BASE}/control/credentials/{user}", timeout=10).json()

    all_ok = True
    for s in task["steps"]:
        all_ok = run_step(task, s, creds[s]) and all_ok
        time.sleep(PAUSE)

    db()["tasks"].update_one({"_id": tid}, {"$set": {
        "status": "done" if all_ok else "needs_attention", "leaseExpiresAt": None}})
    emit(tid, "task", "verified" if all_ok else "failed",
         "all access proven dead" if all_ok else "some steps unverified: needs a human")

    try:
        summary = narrate.audit_summary(tid, user, all_ok)  # Groq: explains, never decides
        if summary:
            emit(tid, "task", "verified" if all_ok else "failed", "AUDIT SUMMARY (Groq): " + summary)
    finally:
        stop.set()
        heartbeat_thread.join()


def main():
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))
    warm_up()
    owner = f"agent-{uuid.uuid4().hex[:6]}"
    print(f"{owner} up (pid {os.getpid()}), waiting for work...")
    while True:
        task = claim(owner)
        if task is None:
            time.sleep(1)
            continue
        process_task(owner, task)


if __name__ == "__main__":
    main()