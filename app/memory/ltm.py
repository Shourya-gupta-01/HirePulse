import logging
import re
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
        """Store or update a fact in long-term memory with fast duplicate check and semantic deduplication."""
        text = text.strip()
        if not text:
            return {"id": "", "action": "empty"}

        uid_str = str(user_id)

        # 1. Fast exact duplicate check via direct DB query (10ms)
        try:
            existing_all = self.get_all_memories(user_id=uid_str)
            for m in existing_all:
                if m.get("memory", "").strip().lower() == text.lower():
                    return {"id": m.get("id", ""), "action": "exact_duplicate"}
        except Exception as exc:
            logger.warning("Error during fast duplicate check: %s", exc)

        # 2. Semantic near-duplicate / update check via vector search
        try:
            existing = self.vectorstore.similarity_search_with_relevance_scores(
                text, k=1, filter={"user_id": uid_str}
            )
            if existing:
                doc, score = existing[0]
                existing_id = doc.metadata.get("id") or doc.id

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
        """Retrieve the most relevant long-term memories for a given query with instant keyword matching and vector fallback."""
        if not query or not query.strip():
            return []

        # 1. Fast path: Direct DB query + token/phrase matching (< 10ms) without embedding API overhead
        try:
            all_memories = self.get_all_memories(user_id=user_id)
            if all_memories:
                query_lower = query.lower()
                query_tokens = set(
                    t for t in re.findall(r"\b\w{3,}\b", query_lower)
                    if t not in {"what", "when", "where", "which", "who", "whom", "this", "that", "with", "from", "your", "about", "remember", "recall", "tell", "have"}
                )

                scored = []
                for m in all_memories:
                    text = m.get("memory", "")
                    if not text:
                        continue
                    text_lower = text.lower()
                    score = 0
                    if query_lower in text_lower or text_lower in query_lower:
                        score += 10
                    matches = sum(1 for tok in query_tokens if tok in text_lower)
                    score += matches * 2
                    if score > 0:
                        scored.append((score, text))

                if scored:
                    scored.sort(key=lambda x: x[0], reverse=True)
                    return [text for _, text in scored[:k]]

                # If query was generic (e.g. "what do you know about me?"), return recent facts
                if not query_tokens or len(all_memories) <= k:
                    return [m.get("memory", "") for m in all_memories[:k] if m.get("memory")]
        except Exception as exc:
            logger.warning("Error in fast memory matching: %s", exc)

        # 2. Vector search fallback
        try:
            results = self.vectorstore.similarity_search(
                query,
                k=k,
                filter={"user_id": str(user_id)},
            )
            return [doc.page_content for doc in results if doc.page_content]
        except Exception as exc:
            logger.warning("Error searching memories in PGVector: %s", exc)
            return self.get_recent_memories(user_id=user_id, limit=k)

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

    def get_recent_memories(self, user_id: str = "default_user", limit: int = 5) -> List[str]:
        """Fast DB query to retrieve user's most recent memories/preferences without calling external embedding APIs."""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT e.document
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                        WHERE c.name = %s
                          AND e.cmetadata->>'user_id' = %s
                        ORDER BY e.id DESC
                        LIMIT %s
                        """,
                        (self.collection_name, str(user_id), limit),
                    )
                    rows = cur.fetchall()
                    return [r[0] for r in rows if r[0]]
        except Exception as exc:
            logger.warning("Error reading recent memories from PGVector: %s", exc)
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
