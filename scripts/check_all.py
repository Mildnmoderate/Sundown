import time
from common import config
from common.db import db, client
from common.llm import chat
from common.embed import embed

ok = True
def report(name, passed, detail=""):
    global ok
    ok = ok and passed
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")

# 1. Database: ping, write, read, delete
try:
    client().admin.command("ping")
    c = db()["_healthcheck"]
    _id = c.insert_one({"t": time.time()}).inserted_id
    found = c.find_one({"_id": _id}) is not None
    c.delete_one({"_id": _id})
    report("MongoDB connect + write/read/delete", found)
except Exception as e:
    report("MongoDB connect + write/read/delete", False, str(e)[:150])

# 2. LLM
try:
    out = chat("Reply with the single word OK.", max_tokens=10)
    report("LLM (Groq)", True, f"replied: {out.strip()[:30]}")
except Exception as e:
    report("LLM (Groq)", False, str(e)[:150])

# 3. Embeddings
try:
    v = embed("okta status field renamed to state")
    matches = len(v) == config.EMBED_DIM
    report("Embeddings", matches, f"dimension = {len(v)}" + ("" if matches else f" (EMBED_DIM says {config.EMBED_DIM}, fix .env)"))
except Exception as e:
    report("Embeddings", False, str(e)[:150])

# 4. Vector index
try:
    idx = [i for i in db()["experiences"].list_search_indexes() if i["name"] == config.VECTOR_INDEX]
    report("Vector index", bool(idx) and idx[0].get("queryable", False),
           "ready" if idx and idx[0].get("queryable") else "missing or still building (run scripts.setup_db)")
except Exception as e:
    report("Vector index", False, str(e)[:150])

# 5. Change streams
try:
    with db()["events"].watch(max_await_time_ms=500) as s:
        s.try_next()
    report("Change streams", True)
except Exception as e:
    report("Change streams", False, str(e)[:150])

print("\nALL GOOD, you're ready to build" if ok else "\nFix the FAILs above")