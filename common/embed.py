import httpx
from . import config

_local_model = None

def embed(text: str) -> list[float]:
    if config.EMBED_PROVIDER == "local":
        global _local_model
        if _local_model is None:
            from sentence_transformers import SentenceTransformer
            _local_model = SentenceTransformer("all-MiniLM-L6-v2")  # 384 dims
        return _local_model.encode(text).tolist()

    r = httpx.post(
        config.EMBED_BASE_URL + "/embeddings",
        headers={"Authorization": f"Bearer {config.EMBED_API_KEY}"},
        json={"model": config.EMBED_MODEL, "input": [text]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]