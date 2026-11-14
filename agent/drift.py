import os, datetime as dt
import httpx
from common import config
from common.db import db
from common.embed import embed
from common.llm import chat

BASE = os.environ.get("SYSTEMS_URL", "http://localhost:8001")


def _live_schema(system):
    try:
        r = httpx.get(f"{BASE}/{system}/schema", timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _search(system, symptom):
    pipeline = [
        {"$vectorSearch": {"index": config.VECTOR_INDEX, "path": "embedding",
                           "queryVector": embed(symptom), "numCandidates": 50,
                           "limit": 5, "filter": {"system": system}}},
        {"$project": {"symptom": 1, "fix": 1, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(db()["experiences"].aggregate(pipeline))


def llm_second_opinion(system, status, body, action):
    """Explanation only. The model never picks the fix and never verifies anything."""
    try:
        return chat(
            f"System: {system}\nError: HTTP {status} {body[:300]}\n"
            f"Proposed fix: {action['method']} {action['path']}\n"
            "In one sentence, say what changed in the API and whether the proposed fix addresses it. "
            "Use only the facts given.",
            system="You are a careful SRE assistant. Reply with one sentence.",
            max_tokens=120).strip()
    except Exception:
        return None


def resolve(system, status, body, user):
    symptom = f"{system} API returned HTTP {status}: {body[:300]}"
    hits = _search(system, symptom)
    hit = next((h for h in hits if (h.get("fix") or {}).get("action")), None)
    schema = _live_schema(system)
    live = None
    if schema and schema.get("deactivate"):
        d = schema["deactivate"]
        live = {"method": d["method"], "path": d["path"].replace("{id}", "{user}"),
                "body": {"user_id": "{user}"} if "user_id" in str(d.get("body")) else d.get("body")}

    if hit:
        action, source = hit["fix"]["action"], "vector_search"
        note = (f"matched past experience {str(hit['_id'])[-6:]} (score {hit['score']:.2f}): "
                f"{hit['symptom'][:70]}... applying {action['method']} {action['path']}")
        # sanity check against the system's live schema
        if live and live["path"] != action["path"]:
            action, source = live, "live_schema"
            note += f" | live schema disagrees, using {live['method']} {live['path']} instead"
    elif live:
        action, source, note = live, "live_schema", \
            f"no past experience, read live schema: {live['method']} {live['path']}"
    else:
        return {"ok": False}

    db()["adapters"].update_one(
        {"system": system},
        {"$set": {"system": system, "action": action, "source": source,
                  "at": dt.datetime.now(dt.timezone.utc)}},
        upsert=True)
    if source == "live_schema":                       # learn it for next time
        db()["experiences"].insert_one({
            "system": system, "symptom": symptom,
            "fix": {"type": "change_endpoint", "action": action}, "embedding": embed(symptom),
            "learned": True, "at": dt.datetime.now(dt.timezone.utc)})
    return {"ok": True, "action": action, "source": source, "note": note,
            "experienceId": str(hit["_id"]) if hit else None,
            "score": round(hit["score"], 3) if hit else None,
            "llm_note": llm_second_opinion(system, status, body, action)}