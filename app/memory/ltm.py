import logging
import uuid
from typing import Dict, List, Optional

import psycopg
from langchain_core.documents import Document
from langchain_postgres.vectorstores import PGVector

from app.config import DATABASE_URL
from app.rag.embeddings import embeddings

logger = logging.getLogger(__name__)


def get_pg_connection_url(url: str = DATABASE_URL) -> str:
    """Format standard PostgreSQL connection string for SQLAlchemy/psycopg."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class LongTermMemory:
    """Manages cross-thread persistent user facts, preferences, and context using PGVector."""

    def __init__(self, collection_name: str = "user_long_term_memory"):
        self.collection_name = collection_name
        self.vectorstore = PGVector(
            embeddings=embeddings,
            collection_name=collection_name,
            connection=get_pg_connection_url(),
            use_jsonb=True,
        )

    def add_memory(
        self,
        text: str,
        user_id: str = "default_user",
        category: str = "preference",
        similarity_threshold: float = 0.85,
    ) -> Dict[str, str]:
        """Store or update a fact in long-term memory with semantic deduplication."""
        text = text.strip()
        if not text:
            return {"id": "", "action": "empty"}

        uid_str = str(user_id)

        # Check for existing memory on the same topic for this user
        try:
            existing = self.vectorstore.similarity_search_with_relevance_scores(
                text, k=1, filter={"user_id": uid_str}
            )
            if existing:
                doc, score = existing[0]
                existing_id = doc.metadata.get("id") or doc.id

                # 1. Exact duplicate check (normalized text)
                if doc.page_content.strip().lower() == text.lower():
                    return {"id": str(existing_id), "action": "exact_duplicate"}

                # 2. Semantic near-duplicate / update check
                if score >= similarity_threshold:
                    doc.page_content = text
                    doc.metadata["category"] = category
                    doc.metadata["user_id"] = uid_str
                    # In PGVector, replace the existing document
                    if existing_id:
                        self.vectorstore.delete(ids=[str(existing_id)])
                    new_id = str(existing_id) if existing_id else str(uuid.uuid4())
                    doc.metadata["id"] = new_id
                    self.vectorstore.add_documents([doc], ids=[new_id])
                    return {"id": new_id, "action": "updated"}
        except Exception as exc:
            logger.warning("Error during LTM semantic deduplication check: %s", exc)

        # 3. New distinct memory
        memory_id = str(uuid.uuid4())
        doc = Document(
            page_content=text,
            metadata={
                "id": memory_id,
                "user_id": uid_str,
                "category": category,
            },
        )
        self.vectorstore.add_documents([doc], ids=[memory_id])
        return {"id": memory_id, "action": "created"}

    def search_memories(self, query: str, user_id: str = "default_user", k: int = 4) -> List[str]:
        """Retrieve the most relevant long-term memories for a given query."""
        if not query or not query.strip():
            return []

        try:
            results = self.vectorstore.similarity_search(
                query,
                k=k,
                filter={"user_id": str(user_id)},
            )
            return [doc.page_content for doc in results if doc.page_content]
        except Exception as exc:
            logger.warning("Error searching memories in PGVector: %s", exc)
            return []

    def get_all_memories(self, user_id: str = "default_user") -> List[Dict[str, str]]:
        """List all memories for a user from PGVector."""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT e.id, e.document, e.cmetadata
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                        WHERE c.name = %s
                          AND e.cmetadata->>'user_id' = %s
                        ORDER BY e.id ASC
                        """,
                        (self.collection_name, str(user_id)),
                    )
                    rows = cur.fetchall()
                    memories = []
                    for mid, text, meta in rows:
                        meta = meta or {}
                        memories.append({
                            "id": str(meta.get("id") or mid),
                            "memory": text or "",
                            "category": meta.get("category", "preference"),
                        })
                    return memories
        except Exception as exc:
            logger.warning("Error reading all memories from PGVector: %s", exc)
            return []

    def delete_memory(self, memory_id: str) -> bool:
        """Remove a memory by its unique ID."""
        try:
            self.vectorstore.delete(ids=[str(memory_id)])
            return True
        except Exception as exc:
            logger.error("Error deleting memory %s from PGVector: %s", memory_id, exc)
            return False


# Global singleton instance used across the app
ltm_store = LongTermMemory()
