"""End-to-end suite for Sundown. Needs ./run.sh running (uvicorn on :8001 with AGENT_CMD set).
Usage: python -m scripts.test_all                 (everything, about 4 min)
       python -m scripts.test_all github okta     (only those tests)
Tests: smoke happy github google okta vector groq kill repeat double"""
import sys, time, traceback
import httpx
from bson import ObjectId
from common.db import db

SYSTEMS = ["okta", "github", "slack", "google", "expenses"]
c = httpx.Client(base_url="http://127.0.0.1:8001", timeout=15)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}  {detail}")
    return bool(cond)


def soft(name, cond, detail=""):
    """Informational only: Groq can rate-limit, and the agent must work without it."""
    print(f"  {'ok  ' if cond else 'WARN'}  {name}  {detail}")


def state():
    return c.get("/control/state").json()


def ensure_worker():
    if not state()["agent"]["running"]:
        c.post("/control/start_agent").raise_for_status()
        time.sleep(2)


TOGGLES = {"github": ("github", "lies_on_revoke", True),
           "google": ("google", "delay_seconds", 20),
           "okta": ("okta", "version", "v2")}


def reset(chaos=()):
    c.post("/control/reset", json={"clear_db": True}).raise_for_status()
    c.post("/control/chaos", json={"on": False}).raise_for_status()
    for name in chaos:
        if name == "all":
            c.post("/control/chaos", json={"on": True}).raise_for_status()
        else:
            s, k, v = TOGGLES[name]
            c.post("/control/toggle", json={"system": s, "key": k, "value": v}).raise_for_status()
    time.sleep(1)


def start_task():
    ensure_worker()
    r = c.post("/control/start", json={"employee": "priya"})
    r.raise_for_status()
    return r.json()["taskId"]


def wait_done(tid, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = db()["tasks"].find_one({"_id": ObjectId(tid)})
        if t and t.get("status") in ("done", "needs_attention"):
            return t
        if t and t.get("status") == "pending" and time.time() - t0 > 12:
            ensure_worker()
        time.sleep(1)
    return None


def events(tid, system=None):
    q = {"taskId": tid}
    if system:
        q["system"] = system
    return list(db()["events"].find(q).sort("ts", 1))


def sends(tid, system):
    return db()["events"].count_documents(
        {"taskId": tid, "system": system, "state": "sending", "detail": {"$regex": "^attempt"}})


def steps_ok(t):
    return bool(t) and all(t["steps"][s]["state"] == "verified" for s in t["steps"])


# ---------------------------------------------------------------- tests
def t_smoke():
    check("systems API healthy", c.get("/health").json().get("ok") is True)
    check("5 systems present", all(s in state() for s in SYSTEMS))
    check("Atlas reachable", db().command("ping").get("ok") == 1.0)
    check("experiences seeded (>=6)", db()["experiences"].count_documents({}) >= 6)
    creds = c.get("/control/credentials/priya").json()
    check("credentials endpoint", set(creds) == set(SYSTEMS))


def t_happy():
    reset()
    tid = start_task()
    t = wait_done(tid, 90)
    check("task finished 'done'", t and t["status"] == "done")
    check("all 5 steps verified", steps_ok(t))
    check("every step has passing probe evidence",
          t and all((t["steps"][s].get("evidence") or {}).get("passed") for s in t["steps"]))
    st = state()
    check("GROUND TRUTH: priya has no access anywhere",
          all(st[s]["users"]["priya"] is False for s in SYSTEMS))
    check("BYSTANDER: marcus untouched everywhere",
          all(st[s]["users"]["marcus"] is True for s in SYSTEMS))
    check("no duplicate sends (1 per system)", all(sends(tid, s) == 1 for s in SYSTEMS))
    time.sleep(3)
    t = db()["tasks"].find_one({"_id": ObjectId(tid)})
    soft("Groq audit summary stored", bool(t and t.get("summary")), (t or {}).get("summary", "")[:90])


def t_github():
    reset(["github"])
    tid = start_task()
    t = wait_done(tid, 120)
    check("task done", t and t["status"] == "done")
    evs = events(tid, "github")
    check("lie caught ('STILL works' logged)", any("STILL works" in (e.get("detail") or "") for e in evs))
    esc = [e for e in evs if "revoke_sessions" in (e.get("detail") or "") and e["state"] == "sending"]
    check("escalated to /github/revoke_sessions", len(esc) >= 1)
    ver = [e for e in evs if e["state"] == "verified"]
    check("NEVER verified before the real revoke",
          bool(esc and ver) and min(e["ts"] for e in ver) > min(e["ts"] for e in esc))
    check("github needed 2 attempts", t and t["steps"]["github"]["attempts"] == 2)
    check("ground truth: github access gone", state()["github"]["users"]["priya"] is False)


def t_google():
    reset(["google"])
    t0 = time.time()
    tid = start_task()
    t = wait_done(tid, 120)
    took = time.time() - t0
    check("task done", t and t["status"] == "done")
    check("waited out the ~20s propagation", took >= 18, f"({took:.0f}s)")
    probes = [e for e in events(tid, "google") if "probe #" in (e.get("detail") or "")]
    check("probed repeatedly while waiting", len(probes) >= 2, f"({len(probes)} probes)")
    check("google was NOT resent (1 attempt)", t and t["steps"]["google"]["attempts"] == 1)


def t_okta():
    reset(["okta"])
    tid = start_task()
    t = wait_done(tid, 120)
    check("task done", t and t["status"] == "done")
    ad = [e for e in events(tid, "okta") if e["state"] == "adapted"]
    check("adaptation event logged", len(ad) >= 1)
    ev = (ad[0].get("evidence") or {}) if ad else {}
    check("fix came from VECTOR SEARCH (experienceId present)", ev.get("experienceId") is not None,
          f"(source={ev.get('source')}, score={ev.get('score')})")
    check("adapter saved to Atlas", db()["adapters"].find_one({"system": "okta"}) is not None)
    check("okta verified after adapting", t and t["steps"]["okta"]["state"] == "verified")
    soft("Groq LLM check on the adaptation", ev.get("llm_note") is not None, str(ev.get("llm_note"))[:90])


def t_vector():
    from agent import drift
    hits = drift._search("okta", "okta API returned HTTP 400: endpoint_removed, "
                         "POST /okta/remove_user was removed in API v2")
    check("vector search returns hits", len(hits) > 0)
    top = hits[0] if hits else {}
    check("top hit has an action", bool((top.get("fix") or {}).get("action")),
          f"(score={top.get('score', 0):.2f})")
    gh = drift._search("github", "remove user returned 200 but token still works")
    check("system filter works (github query returns github docs)",
          bool(gh) and all(h["fix"] is not None for h in gh))


def t_groq():
    from agent.drift import llm_second_opinion
    out = llm_second_opinion("okta", 400, "endpoint_removed: POST /okta/remove_user was removed in API v2",
                             {"method": "PUT", "path": "/okta/users/{user}/state"})
    check("Groq answers (check LLM_API_KEY / LLM_MODEL if this fails)", bool(out), str(out)[:100])


def t_kill_resume():
    reset(["all"])
    tid = start_task()
    verified = []
    deadline = time.time() + 70
    while time.time() < deadline:
        t = db()["tasks"].find_one({"_id": ObjectId(tid)}) or {}
        verified = [s for s, v in t.get("steps", {}).items() if v["state"] == "verified"]
        if len(verified) >= 2:
            break
        time.sleep(0.2)
    if not check("reached 2 verified steps before the kill", len(verified) >= 2):
        return
    before = {s: sends(tid, s) for s in verified}
    c.post("/control/kill_agent").raise_for_status()
    time.sleep(1.5)
    check("agent reported stopped after kill", state()["agent"]["running"] is False)
    time.sleep(7)                                   # lease (6s) must expire
    c.post("/control/start_agent").raise_for_status()
    t = wait_done(tid, 150)
    check("task finished after restart", t and t["status"] == "done")
    check("all 5 verified after resume", steps_ok(t))
    skipped = [e["system"] for e in events(tid)
               if "already verified before the crash, skipped" in (e.get("detail") or "")]
    check("verified steps were SKIPPED on resume", all(s in skipped for s in verified), f"({skipped})")
    check("NO re-sends for steps verified before the crash",
          all(sends(tid, s) == before[s] for s in verified))
    check("ground truth: access gone everywhere",
          all(state()[s]["users"]["priya"] is False for s in SYSTEMS))


def t_repeat():
    for i in (1, 2):
        reset(["all"])
        t = wait_done(start_task(), 150)
        check(f"all-chaos run #{i} succeeded", bool(t) and t["status"] == "done" and steps_ok(t))


def t_double_start():
    reset()
    ensure_worker()
    a, b = start_task(), start_task()
    ta, tb = wait_done(a, 120), wait_done(b, 120)
    check("two queued tasks both finish",
          bool(ta and tb) and ta["status"] == "done" and tb["status"] == "done")


TESTS = [("smoke", t_smoke), ("happy", t_happy), ("github", t_github), ("google", t_google),
         ("okta", t_okta), ("vector", t_vector), ("groq", t_groq), ("kill", t_kill_resume),
         ("repeat", t_repeat), ("double", t_double_start)]

if __name__ == "__main__":
    only = set(sys.argv[1:])
    for name, fn in TESTS:
        if only and name not in only:
            continue
        print(f"\n== {name}")
        try:
            fn()
        except Exception as e:
            check(f"{name} crashed", False, repr(e)[:200])
            traceback.print_exc()
    try:
        c.post("/control/chaos", json={"on": False})
    except Exception:
        pass
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    for n, ok in results:
        if not ok:
            print("  FAILED:", n)
    sys.exit(0 if passed == len(results) else 1)