import logging
from pathlib import Path
from typing import Dict, List, Optional

import psycopg
from langchain_community.document_compressors import FlashrankRerank
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_postgres.vectorstores import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
except ImportError:
    from langchain_classic.retrievers import ContextualCompressionRetriever, EnsembleRetriever

from app.config import DATABASE_URL
from app.rag.embeddings import embeddings
from app.rag.loaders import load_file

logger = logging.getLogger(__name__)


def get_pg_connection_url(url: str = DATABASE_URL) -> str:
    """Format standard PostgreSQL connection string for SQLAlchemy/psycopg."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# PGVector vector store for RAG knowledge base
vectorstore = PGVector(
    embeddings=embeddings,
    collection_name="rag_knowledge_base",
    connection=get_pg_connection_url(),
    use_jsonb=True,
)

# Text splitter & lazy cross-encoder reranker
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
_reranker = None

def get_reranker() -> FlashrankRerank:
    global _reranker
    if _reranker is None:
        _reranker = FlashrankRerank(top_n=4)
    return _reranker


class HybridRAG:
    """Hybrid RAG (BM25 keyword search + PGVector dense search + FlashRank reranker).

    Each conversation thread maintains its own isolated pool of documents so
    files uploaded in one chat never leak into another.
    """

    def __init__(self):
        self.vectorstore = vectorstore
        self.thread_chunks: Dict[str, List[Document]] = {}
        self.thread_files: Dict[str, List[str]] = {}
        self._load_existing_threads_from_db()

    def _load_existing_threads_from_db(self):
        """Restore in-memory thread files and chunks from PGVector on startup."""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT e.document, e.cmetadata
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                        WHERE c.name = 'rag_knowledge_base'
                        """
                    )
                    rows = cur.fetchall()
                    for doc_text, meta in rows:
                        meta = meta or {}
                        thread_id = meta.get("thread_id")
                        if not thread_id:
                            continue

                        thread_id_str = str(thread_id)
                        doc = Document(page_content=doc_text, metadata=meta)
                        self.thread_chunks.setdefault(thread_id_str, []).append(doc)

                        filename = meta.get("filename")
                        files_list = self.thread_files.setdefault(thread_id_str, [])
                        if filename and filename not in files_list:
                            files_list.append(filename)
        except Exception as exc:
            logger.warning("Could not restore thread documents from PGVector: %s", exc)

    def ingest_documents(
        self,
        file_paths: Optional[List[str]] = None,
        documents: Optional[List[Document]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, any]:
        """Split documents into chunks and index them into PGVector and thread memory."""
        raw_documents: List[Document] = []
        saved_filenames: List[str] = []

        if documents:
            raw_documents.extend(documents)
            for doc in documents:
                fname = doc.metadata.get("filename") or doc.metadata.get("source") or "unknown"
                if fname not in saved_filenames:
                    saved_filenames.append(fname)

        if file_paths:
            for file_path in file_paths:
                loaded = load_file(file_path, thread_id=thread_id)
                raw_documents.extend(loaded)
                name = Path(file_path).name
                if name not in saved_filenames:
                    saved_filenames.append(name)

        if not raw_documents:
            return {"chunks": 0, "files": []}

        chunks = text_splitter.split_documents(raw_documents)
        self.vectorstore.add_documents(chunks)

        if thread_id:
            thread_id_str = str(thread_id)
            self.thread_chunks.setdefault(thread_id_str, []).extend(chunks)
            thread_file_list = self.thread_files.setdefault(thread_id_str, [])
            for name in saved_filenames:
                if name not in thread_file_list:
                    thread_file_list.append(name)

        return {"chunks": len(chunks), "files": saved_filenames}

    def get_thread_files(self, thread_id: str) -> List[str]:
        """Return the names of files uploaded to a specific chat thread."""
        return list(self.thread_files.get(str(thread_id), []))

    def delete_thread_documents(self, thread_id: str) -> None:
        """Purge indexed chunks and documents for a thread from PGVector."""
        tid = str(thread_id)
        self.thread_chunks.pop(tid, None)
        self.thread_files.pop(tid, None)
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM langchain_pg_embedding e
                        USING langchain_pg_collection c
                        WHERE e.collection_id = c.uuid
                          AND c.name = 'rag_knowledge_base'
                          AND e.cmetadata->>'thread_id' = %s
                        """,
                        (tid,),
                    )
        except Exception as exc:
            logger.error("Error deleting documents from PGVector for thread %s: %s", thread_id, exc)

    def _create_hybrid_retriever(self, chunks: List[Document], thread_id: str):
        """Combine BM25 keyword matching with PGVector vector search, then rerank."""
        sparse_retriever = BM25Retriever.from_documents(chunks)
        sparse_retriever.k = 10

        dense_retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": 10, "filter": {"thread_id": str(thread_id)}}
        )

        hybrid_ensemble = EnsembleRetriever(
            retrievers=[sparse_retriever, dense_retriever],
            weights=[0.5, 0.5],
        )

        return ContextualCompressionRetriever(
            base_compressor=get_reranker(),
            base_retriever=hybrid_ensemble,
        )

    def query(self, query_text: str, thread_id: Optional[str] = None) -> str:
        """Search documents strictly scoped to this thread's uploaded files."""
        chunks = self.thread_chunks.get(str(thread_id), []) if thread_id else []
        if not chunks:
            return "No documents available in knowledge base for this chat yet. Please upload files first."

        retriever = self._create_hybrid_retriever(chunks, thread_id)
        try:
            matched_docs = retriever.invoke(query_text)
        except Exception:
            matched_docs = self.vectorstore.similarity_search(
                query_text, k=4, filter={"thread_id": str(thread_id)}
            )

        if not matched_docs:
            return "No relevant information found in the attached documents for this chat."

        formatted_passages = [
            f"--- Document Source {i}: {doc.metadata.get('filename', 'Unknown')} ---\n{doc.page_content}"
            for i, doc in enumerate(matched_docs, start=1)
        ]
        return "\n\n".join(formatted_passages)


# Global singleton instance used across the app
rag_system = HybridRAG()
