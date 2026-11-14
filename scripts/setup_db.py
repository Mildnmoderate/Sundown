import time
from pymongo.operations import SearchIndexModel
from common import config
from common.db import db

d = db()
existing = d.list_collection_names()
for name in ["tasks", "events", "adapters", "experiences"]:
    if name not in existing:
        d.create_collection(name)
        print("created", name)

d["tasks"].create_index("status")
d["events"].create_index([("taskId", 1), ("ts", 1)])

coll = d["experiences"]
if not any(i["name"] == config.VECTOR_INDEX for i in coll.list_search_indexes()):
    coll.create_search_index(SearchIndexModel(
        name=config.VECTOR_INDEX,
        type="vectorSearch",
        definition={"fields": [
            {"type": "vector", "path": "embedding",
             "numDimensions": config.EMBED_DIM, "similarity": "cosine"},
            {"type": "filter", "path": "system"},
        ]},
    ))
    print(f"vector index requested ({config.EMBED_DIM} dims), building...")

for _ in range(30):
    idx = [i for i in coll.list_search_indexes() if i["name"] == config.VECTOR_INDEX]
    if idx and idx[0].get("queryable"):
        print("vector index READY")
        break
    time.sleep(10)
else:
    print("still building, check Atlas > Search & Vector Search")