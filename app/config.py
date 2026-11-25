import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base filesystem directories
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "Database"
PERSIST_DIR = DB_DIR / "chroma_db"
DOCS_DIR = DB_DIR / "uploads"
DB_PATH = DB_DIR / "Chat_database.db"

# Ensure directories exist
DB_DIR.mkdir(parents=True, exist_ok=True)
PERSIST_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# PostgreSQL Configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "hirepulse")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# MinIO Object Storage Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "hirepulse-uploads")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes")


# File constraints
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".md", ".markdown", ".txt", ".json", ".py", ".log"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

# API Keys & Endpoints
OPENR_API = os.getenv("OPENR_API")
GEMINI_API = os.getenv("GEMINI_API") or os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Langfuse Configuration
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
if LANGFUSE_PUBLIC_KEY:
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
if LANGFUSE_SECRET_KEY:
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
if LANGFUSE_HOST:
    os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST
    os.environ["LANGFUSE_BASE_URL"] = LANGFUSE_HOST

MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-3.3-70b-instruct")
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME", "meta-llama/llama-3.1-8b-instruct")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-2")

# CORS Origins
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
