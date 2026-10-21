"""Conversation memory in MongoDB (or in-process when no MONGO_URI is configured).

* Keys are ``"<principal>:<session_id>"``. The principal comes from the authenticated gateway
  client, so one client cannot read another client's sessions by guessing a session id.
* Documents expire through a TTL index (``memory.retention_days``).
* Only PII-redacted text is stored.
* Memory is best-effort: if MongoDB is down the assistant answers without history
  (short timeouts, no 30 s server-selection hang).
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from datetime import UTC, datetime
from functools import lru_cache

from ai_orchestrator.config import Settings, get_settings

log = logging.getLogger(__name__)


def session_key(principal: str, session_id: str) -> str:
    return f"{principal}:{session_id}"


class ConversationMemory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._local: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._lock = threading.Lock()
        self._indexes_ready = False
        self._collection = None
        if settings.mongo_uri:
            from pymongo import MongoClient

            client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=1500, connectTimeoutMS=1500,
                                 socketTimeoutMS=3000, appname="nexus-orchestrator")
            self._collection = client["nexus_ai_ops"]["conversation_turns"]

    @property
    def backend(self) -> str:
        return "mongodb" if self._collection is not None else "in-process"

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        from pymongo import ASCENDING, DESCENDING

        self._collection.create_index([("session_key", ASCENDING), ("created_at", DESCENDING)])
        self._collection.create_index("created_at", expireAfterSeconds=self.settings.memory_retention_days * 86400)
        self._indexes_ready = True

    def history(self, key: str, turns: int | None = None) -> list[dict]:
        turns = turns or self.settings.memory_turns
        if self._collection is None:
            with self._lock:
                return list(self._local[key])[-turns:]
        try:
            self._ensure_indexes()
            docs = self._collection.find({"session_key": key}, {"_id": 0, "user": 1, "assistant": 1}) \
                .sort("created_at", -1).limit(turns)
            return list(docs)[::-1]
        except Exception as exc:  # pymongo raises several error types; memory is best-effort
            log.warning("Memory read failed (%s); continuing without history", exc)
            return []

    def append(self, key: str, user: str, assistant: str, metadata: dict | None = None) -> bool:
        turn = {"user": user, "assistant": assistant}
        if self._collection is None:
            with self._lock:
                self._local[key].append(turn)
            return True
        try:
            self._ensure_indexes()
            self._collection.insert_one({"session_key": key, **turn, "metadata": metadata or {},
                                         "created_at": datetime.now(UTC)})
            return True
        except Exception as exc:
            log.warning("Memory write failed (%s)", exc)
            return False


@lru_cache(maxsize=1)
def get_memory() -> ConversationMemory:
    return ConversationMemory(get_settings())
