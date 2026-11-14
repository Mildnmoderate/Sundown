import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "sundown")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "local")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "384"))
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", "")
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "")

VECTOR_INDEX = "experiences_vector"