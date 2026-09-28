import os
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

class LongTermAgentMemory:
    def __init__(self):
        # Establish connection matrix to the active, authenticated MongoDB cluster
        mongo_uri = os.getenv("MONGO_URI", "mongodb://nexus_admin:nexus_secure_password@localhost:27017/")
        self.client = MongoClient(mongo_uri)
        self.db = self.client["nexus_ai_ops"]
        self.collection = self.db["agent_conversations"]

    def persist_state_trace(self, session_id: str, query: str, response: str, metadata: dict = None) -> str:
        """
        Saves contextual telemetry loops dynamically to unstructured databases.
        Implements polymorphic document layouts to handle complex runtime variables.
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        payload = {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc),
            "user_query": query,
            "agent_resolution": response,
            "polymorphic_metadata": metadata or {}
        }

        try:
            self.collection.insert_one(payload)
            print(f"💾 [NoSQL Layer] Context trace persisted safely under Session: {session_id}")
            return session_id
        except Exception as e:
            print(f"⚠️ [NoSQL Layer Error] Failed to write memory log: {str(e)}")
            return session_id

    def retrieve_recent_conversation_history(self, session_id: str, limit: int = 3) -> str:
        """
        Fetches historical interaction contexts matching the session token.
        Formats the document matrix into a clean semantic text bundle for context injection.
        """
        if not session_id:
            return ""

        try:
            # Match records, sorting backwards sequentially by timestamp
            cursor = self.collection.find({"session_id": session_id}).sort("timestamp", -1).limit(limit)
            history_blocks = list(cursor)[::-1] # Reverse list to maintain correct chronological order

            if not history_blocks:
                return "No previous conversational memory found for this session."

            formatted_history = ""
            for record in history_blocks:
                formatted_history += f"\nUser: {record.get('user_query')}\nAgent: {record.get('agent_resolution')}\n"
            return formatted_history

        except Exception as e:
            print(f"⚠️ [NoSQL Layer Error] History retrieval failure: {str(e)}")
            return ""
