from fastapi import APIRouter, Depends, HTTPException
from app.auth.security import get_current_user
from app.memory.stm import get_user_threads, is_thread_owner

from app.agent.graph import get_thread_messages
from app.core.storage import storage
from app.memory.stm import get_hidden_threads, get_threads, hide_thread
from app.rag.pipeline import rag_system

router = APIRouter()


def get_thread_title(thread_id: str) -> str:
    """Generate a clean title for a thread based on user input or uploaded docs."""
    messages = get_thread_messages(thread_id)
    for msg in messages:
        if msg["role"] == "user" and msg["content"].strip():
            text = msg["content"].strip().replace("\n", " ")
            return text[:42] + ("..." if len(text) > 42 else "")
    files = rag_system.get_thread_files(thread_id) or storage.list_thread_files(thread_id)
    if files:
        return f"Doc: {files[0]}"
    return "New Chat"


@router.get("/threads")
def list_threads(current_user: dict = Depends(get_current_user)):
    thread_ids = get_user_threads(current_user["id"])
    hidden = get_hidden_threads()
    # Also include any active threads that have uploaded files even before the first message
    for tid in rag_system.thread_files.keys():
        if tid not in thread_ids and tid not in hidden and is_thread_owner(current_user['id'], tid):
            thread_ids.append(tid)

    result = []
    for tid in thread_ids:
        msgs = get_thread_messages(tid)
        files = rag_system.get_thread_files(tid)
        title = "New Chat"
        for msg in msgs:
            if msg["role"] == "user" and msg["content"].strip():
                text = msg["content"].strip().replace("\n", " ")
                title = text[:42] + ("..." if len(text) > 42 else "")
                break
        if title == "New Chat" and files:
            title = f"Doc: {files[0]}"

        result.append({
            "id": tid,
            "title": title,
            "files": files,
        })

    return {"threads": result}


@router.get("/threads/{thread_id}/messages")
def thread_messages(thread_id: str, current_user: dict = Depends(get_current_user)):
    if not is_thread_owner(current_user['id'], thread_id):
        raise HTTPException(status_code = 403, detail = "Access Denied")    
    
    return {
        "thread_id": thread_id,
        "messages": get_thread_messages(thread_id),
        "files": rag_system.get_thread_files(thread_id) or storage.list_thread_files(thread_id),
    }

@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, current_user: dict = Depends(get_current_user)):
    # Soft delete: mark thread as hidden from frontend while preserving full history in database
    if not is_thread_owner(current_user['id'], thread_id):
        raise HTTPException(status_code = 403, detail = "Access Denied")
    hide_thread(thread_id)
    rag_system.delete_thread_documents(thread_id)
    return {"deleted": thread_id, "preserved_in_db": True}


@router.get("/threads/{thread_id}/files")
def list_thread_files(thread_id: str, current_user: dict = Depends(get_current_user)):
    if not is_thread_owner(current_user['id'], thread_id):
        raise HTTPException(status_code = 403, detail = "Access Denied")
    files = rag_system.get_thread_files(thread_id) or storage.list_thread_files(thread_id)
    return {
        "thread_id": thread_id,
        "files": files,
    }
