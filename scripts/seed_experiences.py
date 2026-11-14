from common.db import db
from common.embed import embed

SEED = [
  {"system": "okta", "symptom": "okta returned 400 endpoint removed after an API version bump, deactivate moved to a per-user state endpoint",
   "fix": {"type": "change_endpoint", "action": {"method": "PUT", "path": "/okta/users/{user}/state", "body": {"state": "deprovisioned"}}}},
  {"system": "okta", "symptom": "okta returned 429 rate limited, too many requests, retry after a delay",
   "fix": {"type": "backoff"}},
  {"system": "okta", "symptom": "okta user status field missing in response, status renamed to state",
   "fix": {"type": "remap_field", "from": "status", "to": "state"}},
  {"system": "slack", "symptom": "slack returned 400 field active renamed to deactivated",
   "fix": {"type": "remap_field", "from": "active", "to": "deactivated"}},
  {"system": "github", "symptom": "github remove user returned 200 but the token still works, sessions must be revoked separately",
   "fix": {"type": "escalate", "action": {"method": "POST", "path": "/github/revoke_sessions", "body": {"user_id": "{user}"}}}},
  {"system": "google", "symptom": "google workspace suspend succeeded but token still valid, revocation propagates slowly",
   "fix": {"type": "wait_and_reprobe"}},
]

d = db()["experiences"]
d.delete_many({})
for s in SEED:
    s["embedding"] = embed(s["symptom"])
d.insert_many(SEED)
print("seeded", len(SEED), "experiences. Vector index needs ~10s to catch up.")
