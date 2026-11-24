"""HirePulse Long-Term Memory (LTM) Module.

Provides persistent vector-backed storage for user preferences and facts across threads using PGVector.
"""

from app.rag.embeddings import embeddings
from app.memory.ltm import LongTermMemory, ltm_store
from app.agent.tools.memory_tools import save_user_memory, recall_user_memories

__all__ = [
    "embeddings",
    "LongTermMemory",
    "ltm_store",
    "save_user_memory",
    "recall_user_memories",
]
