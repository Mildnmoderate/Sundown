from pymongo import MongoClient
from . import config

_client = None

def client():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client

def db():
    return client()[config.MONGODB_DB]