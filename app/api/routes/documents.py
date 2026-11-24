import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from app.core.storage import storage
from app.rag.loaders import load_bytes
from app.rag.pipeline import rag_system

router = APIRouter()


@router.post("/documents/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    thread_id: Optional[str] = Form(None),
):
    """Upload documents directly to MinIO container and index chunks into PGVector."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    active_tid = thread_id or str(uuid.uuid4())
    uploaded_objects = []
    all_parsed_docs = []
    skipped_files = []

    for file in files:
        filename = os.path.basename(file.filename or "")
        ext = os.path.splitext(filename)[1].lower()

        if not filename or ext not in ALLOWED_EXTENSIONS:
            skipped_files.append({"name": filename, "reason": f"Unsupported format ({ext or 'none'})"})
            continue

        # Read into memory checking max file size limit
        file_bytes = bytearray()
        size = 0
        try:
            while chunk := await file.read(1024 * 1024):  # 1MB buffer
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File {filename} exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit",
                    )
                file_bytes.extend(chunk)

            raw_bytes = bytes(file_bytes)

            # 1. Store in MinIO object storage container
            object_name = f"{active_tid}/{filename}"
            storage.upload_file(
                data=raw_bytes,
                object_name=object_name,
                content_type=file.content_type or "application/octet-stream",
            )
            uploaded_objects.append(filename)

            # 2. Parse document bytes into chunks for RAG
            docs = load_bytes(raw_bytes, filename=filename, thread_id=active_tid)
            all_parsed_docs.extend(docs)

        except HTTPException:
            raise
        except Exception as e:
            skipped_files.append({"name": filename, "reason": str(e)})

    if not uploaded_objects:
        raise HTTPException(
            status_code=400,
            detail=f"No valid files were uploaded. Skipped: {skipped_files}",
        )

    # 3. Index parsed documents into PGVector
    try:
        ingest_result = rag_system.ingest_documents(documents=all_parsed_docs, thread_id=active_tid)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to index documents into PGVector: {str(e)}",
        )

    return {
        "success": True,
        "thread_id": active_tid,
        "indexed_chunks": ingest_result.get("chunks", 0),
        "uploaded_files": uploaded_objects,
        "all_thread_files": rag_system.get_thread_files(active_tid),
        "skipped": skipped_files,
    }


@router.get("/documents/{thread_id}/{filename}")
def download_document(thread_id: str, filename: str):
    """Download a file directly from MinIO object storage."""
    object_name = f"{thread_id}/{filename}"
    try:
        content = storage.download_file(object_name)
        ext = os.path.splitext(filename)[1].lower()
        media_type = "application/pdf" if ext == ".pdf" else "text/plain"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found in storage: {str(e)}")
