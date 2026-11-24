import os
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from server import app
from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
from app.core.storage import storage
from app.memory.ltm import ltm_store
from app.memory.stm import get_threads, get_hidden_threads
from app.rag.pipeline import rag_system
from app.rag.loaders import load_bytes

client = TestClient(app)


# =====================================================================
# 1. System Health & Langfuse Integration Tests
# =====================================================================

def test_health_check():
    """Verify system health endpoint returns 200 OK."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_langfuse_callback_handler_initialization():
    """Verify Langfuse v5 CallbackHandler initializes without TypeError."""
    if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
        from langfuse.langchain import CallbackHandler
        handler = CallbackHandler()
        assert handler is not None


# =====================================================================
# 2. Conversational Memory & Thread History (STM / PG Checkpoints)
# =====================================================================

def test_chat_streaming_and_thread_checkpoint_persistence():
    """Verify chatting creates a thread checkpoint in PostgreSQL and retrieves messages."""
    # 1. Send first chat message
    res = client.post("/api/chat", json={"message": "My preferred job role is Senior Site Reliability Engineer."})
    assert res.status_code == 200

    # Parse SSE stream to find thread_id
    thread_id = None
    stream_content = ""
    for line in res.text.split("\n"):
        if line.startswith("data: "):
            try:
                evt = json.loads(line[6:].strip())
                if evt.get("type") == "meta":
                    thread_id = evt.get("thread_id")
                elif evt.get("type") == "token":
                    stream_content += evt.get("content", "")
            except Exception:
                pass

    assert thread_id is not None
    assert len(stream_content) > 0

    # 2. Verify thread appears in GET /api/threads (ordered by latest activity)
    threads_res = client.get("/api/threads")
    assert threads_res.status_code == 200
    threads_list = threads_res.json().get("threads", [])
    thread_entry = next((t for t in threads_list if t["id"] == thread_id), None)
    assert thread_entry is not None
    assert "Senior Site Relia" in thread_entry["title"]

    # 3. Verify messages are retrieved with role and text content
    msgs_res = client.get(f"/api/threads/{thread_id}/messages")
    assert msgs_res.status_code == 200
    messages = msgs_res.json().get("messages", [])
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert "Senior Site Reliability Engineer" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"

    # 4. Soft-delete the thread
    del_res = client.delete(f"/api/threads/{thread_id}")
    assert del_res.status_code == 200
    assert del_res.json().get("deleted") == thread_id

    # 5. Verify it is excluded from /api/threads after deletion
    updated_threads = client.get("/api/threads").json().get("threads", [])
    assert not any(t["id"] == thread_id for t in updated_threads)


# =====================================================================
# 3. Document Ingestion, MinIO Storage & PGVector Hybrid RAG
# =====================================================================

def test_document_upload_minio_and_pgvector_rag():
    """Verify document upload to MinIO, PGVector indexing, and thread-scoped retrieval."""
    thread_id = f"test-e2e-rag-thread-{uuid.uuid4().hex[:6]}"
    doc_content = (
        b"# Technical Specification: Cloud Storage Engine\n\n"
        b"The HirePulse Cloud Storage Engine integrates with MinIO for S3-compatible raw file storage "
        b"and PGVector for high-dimensional vector search. System latency target is under 50ms."
    )
    filename = "storage_spec.md"

    # 1. Upload file via API
    upload_res = client.post(
        "/api/documents/upload",
        data={"thread_id": thread_id},
        files={"files": (filename, doc_content, "text/markdown")},
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["success"] is True
    assert upload_data["thread_id"] == thread_id
    assert filename in upload_data["uploaded_files"]

    # 2. Verify file is persisted in MinIO
    minio_files = storage.list_thread_files(thread_id)
    assert filename in minio_files

    # 3. Verify file download endpoint streams exact content from MinIO
    dl_res = client.get(f"/api/documents/{thread_id}/{filename}")
    assert dl_res.status_code == 200
    assert dl_res.content == doc_content

    # 4. Query RAG scoped to this thread
    query_result = rag_system.query("What is the system latency target?", thread_id=thread_id)
    assert "50ms" in query_result or "latency target" in query_result

    # 5. Cross-thread isolation test: a different thread cannot see this document
    isolation_query = rag_system.query("What is the system latency target?", thread_id="unrelated-empty-thread-999")
    assert "No documents available" in isolation_query

    # 6. Cleanup
    storage.delete_thread_files(thread_id)
    rag_system.delete_thread_documents(thread_id)


# =====================================================================
# 4. Long-Term Memory (LTM) PGVector Lifecycle & API Routes
# =====================================================================

def test_long_term_memory_pgvector_and_api_routes():
    """Verify LTM semantic storage, deduplication, search, and /api/memories endpoints."""
    user_id = f"e2e_test_user_{uuid.uuid4().hex[:8]}"
    fact_text = "Candidate is fluent in Rust, Python, and distributed Kubernetes deployments."

    # 1. Create memory via API
    create_res = client.post(
        "/api/memories",
        json={"text": fact_text, "user_id": user_id, "category": "skill"},
    )
    assert create_res.status_code == 200
    created_data = create_res.json()
    assert created_data["action"] == "created"
    mem_id = created_data["id"]

    # 2. Verify duplicate detection
    dup_res = client.post(
        "/api/memories",
        json={"text": fact_text, "user_id": user_id},
    )
    assert dup_res.status_code == 200
    assert dup_res.json()["action"] == "exact_duplicate"

    # 3. List memories via API
    list_res = client.get(f"/api/memories?user_id={user_id}")
    assert list_res.status_code == 200
    memories_list = list_res.json().get("memories", [])
    assert any(m["id"] == mem_id for m in memories_list)

    # 4. Semantic search in PGVector
    matches = ltm_store.search_memories("What programming languages does the candidate know?", user_id=user_id)
    assert len(matches) > 0
    assert "Rust" in matches[0]

    # 5. Delete memory via API
    del_mem_res = client.delete(f"/api/memories/{mem_id}")
    assert del_mem_res.status_code == 200
    assert del_mem_res.json()["success"] is True

    # 6. Verify deletion
    post_del_list = client.get(f"/api/memories?user_id={user_id}").json().get("memories", [])
    assert not any(m["id"] == mem_id for m in post_del_list)
