import os
import tempfile
from pathlib import Path
from typing import List, Optional

from langchain_community.document_loaders import CSVLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document

def load_file(file_path: str, thread_id: Optional[str] = None) -> List[Document]:
    """Parse PDF, CSV, or text/markdown into standard Documents with thread metadata."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(str(path))
    elif ext == ".csv":
        try:
            loader = CSVLoader(str(path), encoding="utf-8")
        except UnicodeDecodeError:
            loader = CSVLoader(str(path), encoding="latin-1")
    elif ext in {".md", ".markdown", ".txt", ".json", ".py", ".log"}:
        try:
            loader = TextLoader(str(path), encoding="utf-8")
        except UnicodeDecodeError:
            loader = TextLoader(str(path), encoding="latin-1")
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    docs = loader.load()

    # Tag every document with source filename and thread owner
    for doc in docs:
        doc.metadata["source"] = path.name
        doc.metadata["filename"] = path.name
        if thread_id:
            doc.metadata["thread_id"] = str(thread_id)

    return docs


def load_bytes(content: bytes, filename: str, thread_id: Optional[str] = None) -> List[Document]:
    """Parse document bytes using a temporary file that is automatically cleaned up."""
    ext = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        docs = load_file(tmp_path, thread_id=thread_id)
        # Update metadata to reflect actual filename rather than temporary file path
        for doc in docs:
            doc.metadata["source"] = filename
            doc.metadata["filename"] = filename
        return docs
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

